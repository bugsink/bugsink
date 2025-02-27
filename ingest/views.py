import os
import logging
import io
from datetime import datetime, timezone
import json
import jsonschema
import fastjsonschema

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.db.models import Max
from django.views import View
from django.core import exceptions
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import user_passes_test

from compat.auth import parse_auth_header_value
from compat.dsn import get_sentry_key, build_dsn

from projects.models import Project
from issues.models import Issue, IssueStateManager, Grouping, TurningPoint, TurningPointKind
from issues.utils import get_type_and_value_for_data, get_issue_grouper_for_data, get_denormalized_fields_for_data
from issues.regressions import issue_is_regression

from bugsink.transaction import immediate_atomic, delay_on_commit
from bugsink.exceptions import ViolatedExpectation
from bugsink.streams import content_encoding_reader, MaxDataReader, MaxDataWriter, NullWriter, MaxLengthExceeded
from bugsink.app_settings import get_settings

from events.models import Event
from events.retention import evict_for_max_events, should_evict
from releases.models import create_release_if_needed
from alerts.tasks import send_new_issue_alert, send_regression_alert
from compat.timestamp import format_timestamp, parse_timestamp
from tags.models import digest_tags

from .parsers import StreamingEnvelopeParser, ParseError
from .filestore import get_filename_for_event_id
from .tasks import digest
from .event_counter import check_for_thresholds
from .models import StoreEnvelope, DontStoreEnvelope, Envelope


HTTP_429_TOO_MANY_REQUESTS = 429
HTTP_400_BAD_REQUEST = 400
HTTP_501_NOT_IMPLEMENTED = 501


logger = logging.getLogger("bugsink.ingest")
performance_logger = logging.getLogger("bugsink.performance.ingest")


@method_decorator(csrf_exempt, name='dispatch')
class BaseIngestAPIView(View):

    @staticmethod
    def _set_cors_headers(response):
        # For in-browser SDKs, we need to set the CORS headers, because if we don't, the browser will block the response
        # from being read and print an error in the console; the longer version is:
        #
        # CORS protects the user of a browser from some random website "A" sending requests to the API of some site "B";
        # implemented by the the browser enforcing the "Access-Control-Allow-Origin" response header as set by server B.
        # In this case, the "other website B" is the Bugsink server, and the "random website A" is the application that
        # is being monitored. The user has no relationship with the Bugsink API (there's nothing to protect), so we need
        # to tell the browser to not protect against Bugsink data from reaching the monitored application, i.e.
        # Access-Control-Allow-Origin: *.

        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"

        response["Access-Control-Allow-Headers"] = (
            # The following 2 headers are actually understood by us:
            "Content-Type, X-Sentry-Auth, "

            # The following list of headers may be sent by Sentry SDKs. Even if we don't use them, we list them, because
            # any not-listed header is not allowed by the browser and would trip the CORS protection:
            "X-Requested-With, Origin, Accept, Authentication, Authorization, Content-Encoding, sentry-trace, "
            "baggage, X-CSRFToken"
        )

        return response

    def options(self, request, project_pk=None):
        # This is a CORS preflight request; we just return the headers that the browser expects. (we _could_ check for
        # the Origin, Request-Method, etc. headers, but we don't need to)
        result = HttpResponse()
        self._set_cors_headers(result)
        result["Access-Control-Max-Age"] = "3600"  # tell browser to cache to avoid repeated preflight requests
        return result

    def post(self, request, project_pk=None):
        try:
            return self._set_cors_headers(self._post(request, project_pk))
        except MaxLengthExceeded as e:
            return self._set_cors_headers(JsonResponse({"message": str(e)}, status=HTTP_400_BAD_REQUEST))
        except exceptions.ValidationError as e:
            return self._set_cors_headers(JsonResponse({"message": str(e)}, status=HTTP_400_BAD_REQUEST))

    @classmethod
    def get_sentry_key_for_request(cls, request):
        # we simply pick the first authentication mechanism that matches, rather than raising a SuspiciousOperation as
        # sentry does (I found the supplied reasons unconvincing). See https://github.com/getsentry/relay/pull/602

        # "In situations where it's not possible to send [..] header, it's possible [..] values via the querystring"
        # https://github.com/getsentry/develop/blob/b24a602de05b/src/docs/sdk/overview.mdx#L171
        if "sentry_key" in request.GET:
            return request.GET["sentry_key"]

        # Sentry used to support HTTP_AUTHORIZATION too, but that is unused since Sept. 27 2011
        if "HTTP_X_SENTRY_AUTH" in request.META:
            auth_dict = parse_auth_header_value(request.META["HTTP_X_SENTRY_AUTH"])
            return auth_dict.get("sentry_key")

        raise exceptions.PermissionDenied("Unable to find authentication information")

    @classmethod
    def get_project(cls, project_pk, sentry_key):
        try:
            return Project.objects.get(pk=project_pk, sentry_key=sentry_key)
        except Project.DoesNotExist:
            # We don't distinguish between "project not found" and "key incorrect"; there's no real value in that from
            # the user perspective (they deal in dsns). Additional advantage: no need to do constant-time-comp on
            # project.sentry_key for security reasons in that case.
            #
            # The dsn we show is reconstructed _as we understand it at this point in the code_, which is precisely what
            # you want to show as a first step towards debugging issues with SDKs with faulty authentication (a rather
            # common scenario).
            dsn = build_dsn(str(get_settings().BASE_URL), project_pk, sentry_key)
            raise exceptions.PermissionDenied("Project not found or key incorrect: %s" % dsn) from None

    @classmethod
    def get_project_for_request(cls, project_pk, request):
        sentry_key = cls.get_sentry_key_for_request(request)
        return cls.get_project(project_pk, sentry_key)

    @classmethod
    def process_event(cls, ingested_at, event_id, event_data_stream, project, request):
        event_metadata = cls.get_event_meta(event_id, ingested_at, request, project)

        if get_settings().DIGEST_IMMEDIATELY:
            # in this case the stream will be an BytesIO object, so we can actually call .get_value() on it.
            event_data_bytes = event_data_stream.getvalue()
            event_data = json.loads(event_data_bytes.decode("utf-8"))
            performance_logger.info("ingested event with %s bytes", len(event_data_bytes))
            cls.digest_event(event_metadata, event_data)
        else:
            # In this case the stream will be a file that has been written the event's content to it.
            # To ensure that the (possibly EAGER) handling of the digest has the file available, we flush it here:
            event_data_stream.flush()

            performance_logger.info("ingested event with %s bytes", event_data_stream.bytes_written)
            digest.delay(event_id, event_metadata)

    @classmethod
    def get_event_meta(cls, event_id, ingested_at, request, project):
        # Meta means: not part of the event data. Basically: information that is available at the time of ingestion, and
        # that must be passed to digest() in a serializable form.
        debug_info = request.META.get("HTTP_X_BUGSINK_DEBUGINFO", "")
        return {
            "event_id": event_id,
            "project_id": project.id,
            "ingested_at": format_timestamp(ingested_at),
            "debug_info": debug_info,
        }

    @classmethod
    def validate_event_data(cls, data, validation_setting):
        # rough notes on performance (50k event):
        # fastjsonschema: load-from-disk (precompiled): ~1ms, validation: ~2ms
        # jsonschema: 'compile': ~2ms, validation ~15ms
        #
        # note that this method raising an exception ("strict") creates additional overhead in the ~100ms range;
        # presumably because of the transaction rollback. Possible future direction: check pre-transaction. Not
        # optimizing that yet though, because [1] presumably rare and [2] incorrect data might trigger arbitrary
        # exceptions, so you'd have that cost-of-rollback anyway.

        def get_schema():
            schema_filename = settings.BASE_DIR / 'api/event.schema.altered.json'
            with open(schema_filename, 'r') as f:
                return json.loads(f.read())

        def validate():
            # helper function that wraps the idea of "validate quickly, but fail meaningfully"
            try:
                cls._event_validator(data_to_validate)
            except fastjsonschema.exceptions.JsonSchemaValueException as fastjsonschema_e:
                # fastjsonchema's exceptions provide almost no information (in the case of many anyOfs), so we just fall
                # back to jsonschema for that. Slow (and double cost), but failing is the rare case, so we don't care.
                # https://github.com/horejsek/python-fastjsonschema/issues/72 and 37 for some context
                try:
                    jsonschema.validate(data_to_validate, get_schema())
                except jsonschema.ValidationError as inner_e:
                    best = jsonschema.exceptions.best_match([inner_e])
                    # we raise 'from best' here; this does lose some information w.r.t. 'from inner_e', but it's my
                    # belief that it's not useful info we're losing. similarly, but more so for 'fastjsonschema_e'.
                    raise ValidationError(best.json_path + ": " + best.message, code="invalid_event_data") from best

                # in the (presumably not-happening) case that our fallback validation succeeds, fail w/o useful message
                raise ValidationError(fastjsonschema_e.message, code="invalid_event_data") from fastjsonschema_e

        # the schema is loaded once and cached on the class (it's in the 1-2ms range, but my measurements varied a lot
        # so I'm not sure and I'd rather cache (and not always load) a file in the 2.5MB range than to just assume it's
        # fast)
        if not hasattr(cls, "_event_validator"):
            from bugsink.event_schema import validate as validate_schema
            cls._event_validator = validate_schema

        # known fields that are not part of the schema (and that we don't want to validate)
        data_to_validate = {k: v for k, v in data.items() if k != "_meta"}

        if validation_setting == "strict":
            validate()

        else:  # i.e. "warn" - we never reach this function for "none"
            try:
                validate()
            except ValidationError as e:
                logger.warning("event data validation failed: %s", e)

    @classmethod
    @immediate_atomic()
    def digest_event(cls, event_metadata, event_data, digested_at=None):
        # ingested_at is passed from the point-of-ingestion; digested_at is determined here. Because this happens inside
        # `immediate_atomic`, we know digestions are serialized, and assuming non-decreasing server clocks, not decrea-
        # sing. (no so for ingestion times: clock-watching happens outside the snappe transaction, and threading in the
        # foreman is another source of shuffling).
        #
        # Because of this property we use digested_at for eviction and quota, and, because quota is a VBC-based and so
        # is unmuting, in all ummuting-related checks. This saves us from having to precisely reason about edge-cases
        # for non-increasing time, and the drawbacks are minimal, because the differences in time between ingest and
        # digest are assumed to be relatively small, and as a user you don't really care (to the second) which
        # timestamps trigger the quota/eviction.
        #
        # For other user-facing elements in the UI we prefer ingested_at though, because that's closer to the time
        # something actually happened, and that's usually what you care for while debugging.
        ingested_at = parse_timestamp(event_metadata["ingested_at"])
        digested_at = datetime.now(timezone.utc) if digested_at is None else digested_at  # explicit passing: test only

        project = Project.objects.get(pk=event_metadata["project_id"])

        if not cls.count_project_periods_and_act_on_it(project, digested_at):
            return  # if over-quota: just return (any cleanup is done calling-side)

        if get_settings().VALIDATE_ON_DIGEST in ["warn", "strict"]:
            cls.validate_event_data(event_data, get_settings().VALIDATE_ON_DIGEST)

        # I resisted the temptation to put `get_denormalized_fields_for_data` in an if-statement: you basically "always"
        # need this info... except when duplicate event-ids are sent. But the latter is the exception, and putting this
        # in an if-statement would require more rework (and possibly extra queries) than it's worth.
        denormalized_fields = get_denormalized_fields_for_data(event_data)
        # the 3 lines below are suggestive of a further inlining of the get_type_and_value_for_data function
        calculated_type, calculated_value = get_type_and_value_for_data(event_data)
        denormalized_fields["calculated_type"] = calculated_type
        denormalized_fields["calculated_value"] = calculated_value

        grouping_key = get_issue_grouper_for_data(event_data, calculated_type, calculated_value)

        if not Grouping.objects.filter(project_id=event_metadata["project_id"], grouping_key=grouping_key).exists():
            # we don't have Project.issue_count here ('premature optimization') so we just do an aggregate instead.
            max_current = Issue.objects.filter(project_id=event_metadata["project_id"]).aggregate(
                Max("digest_order"))["digest_order__max"]
            issue_digest_order = max_current + 1 if max_current is not None else 1

            # at this point in the code, "new grouper" implies "new issue", because manual information ("this grouper is
            # actually part of some other issue") can by definition not yet have been specified.
            issue = Issue.objects.create(
                digest_order=issue_digest_order,
                project_id=event_metadata["project_id"],
                first_seen=ingested_at,
                last_seen=ingested_at,
                digested_event_count=1,
                stored_event_count=0,  # we increment this below
                **denormalized_fields,
            )
            issue_created = True

            grouping = Grouping.objects.create(
                project_id=event_metadata["project_id"],
                grouping_key=grouping_key,
                issue=issue,
            )

        else:
            grouping = Grouping.objects.get(project_id=event_metadata["project_id"], grouping_key=grouping_key)
            issue = grouping.issue
            issue_created = False

            # update the denormalized fields
            issue.last_seen = ingested_at
            issue.digested_event_count += 1

        # +1 because we're about to add one event.
        project_stored_event_count = project.stored_event_count + 1

        if should_evict(project, digested_at, project_stored_event_count):
            # Note: I considered pushing this into some async process, but it makes reasoning much harder, and it's
            # doubtful whether it would help, because in the end there's just a single pipeline of ingested-related
            # stuff todo, might as well do the work straight away. Similar thoughts about pushing this into something
            # cron-like. (not exactly the same, because for cron-like time savings are possible if the cron-likeness
            # causes the work to be outside of the 'rush hour' -- OTOH this also introduces a lot of complexity about
            # "what is a limit anyway, if you can go either over it, or work is done before the limit is reached")
            evicted = evict_for_max_events(project, digested_at, project_stored_event_count)
        else:
            evicted = 0

        issue.stored_event_count = issue.stored_event_count + 1 - evicted  # +1 because we're about to add one event
        project.stored_event_count = project_stored_event_count - evicted
        project.save(update_fields=["stored_event_count"])

        event, event_created = Event.from_ingested(
            event_metadata,
            digested_at,
            issue.digested_event_count,
            issue.stored_event_count,
            issue,
            grouping,
            event_data,
            denormalized_fields,
        )
        if not event_created:
            if issue_created:
                # this is a weird case that "should not happen" (but can happen in practice). Namely, when some client
                # sends events with the same event_id (leading to no new event), but different-enough actual data that
                # they lead to new issue-creation. I've already run into this while debugging (and this may in fact be
                # the only realistic scenario): manually editing some sample event but not updating the event_id (nor
                # running send_json with --fresh-id). We raise an exception after cleaning up, to at least avoid getting
                # into an inconsistent state in the DB.
                raise ViolatedExpectation("no event created, but issue created")

            # Validating by letting the DB raise an exception, and only after taking some other actions already, is not
            # "by the book" (some book), but it's the most efficient way of doing it when your basic expectation is that
            # multiple events with the same event_id "don't happen" (i.e. are the result of badly misbehaving clients)
            raise ValidationError("Event already exists", code="event_already_exists")

        release = create_release_if_needed(project, event.release, event, issue)

        if issue_created:
            TurningPoint.objects.create(
                issue=issue, triggering_event=event, timestamp=ingested_at,
                kind=TurningPointKind.FIRST_SEEN)
            event.never_evict = True

            if project.alert_on_new_issue:
                delay_on_commit(send_new_issue_alert, str(issue.id))

        else:
            # new issues cannot be regressions by definition, hence this is in the 'else' branch
            if issue_is_regression(issue, event.release):
                TurningPoint.objects.create(
                    issue=issue, triggering_event=event, timestamp=ingested_at,
                    kind=TurningPointKind.REGRESSED)
                event.never_evict = True

                if project.alert_on_regression:
                    delay_on_commit(send_regression_alert, str(issue.id))

                IssueStateManager.reopen(issue)

            # note that while digesting we _only_ care about .is_muted to determine whether unmuting (and alerting about
            # unmuting) should happen, whether as a result of a VBC or 'after time'. Somewhat counter-intuitively, a
            # 'muted' issue is thus not treated as something to more deeply ignore than an unresolved issue (and in
            # fact, conversely, it may be more loud when the for/until condition runs out). This is in fact analogous to
            # "resolved" issues which are _also_ treated with more "suspicion" than their unresolved counterparts.
            if issue.is_muted and issue.unmute_after is not None and digested_at > issue.unmute_after:
                # note that unmuting on-ingest implies that issues that no longer occur stay muted. I'd say this is what
                # you want: things that no longer happen should _not_ draw your attention, and if you've nicely moved
                # some issue away from the "Open" tab it should not reappear there if a certain amount of time passes.
                # Thus, unmute_after should more completely be called unmute_until_events_happen_after but that's a bit
                # long. Phrased slightly differently: you basically click the button saying "I suppose this issue will
                # self-resolve in x time; notify me if this is not the case"
                IssueStateManager.unmute(
                    issue, triggering_event=event,
                    unmute_metadata={"mute_for": {"unmute_after": issue.unmute_after}})

        if event.never_evict:
            # as a sort of poor man's django-dirtyfields (which we haven't adopted for simplicity's sake) we simply do
            # this manually for a single field; we know that if never_evict has been set, it's always been set after the
            # .create call, i.e. its results still need to be saved. We accept the cost of the extra .save call, since
            # TurningPoints are relatively rare (and hence so is this setting of `never_evict` and the associated save
            # call)
            event.save()

        if release.version + "\n" not in issue.events_at:
            issue.events_at += release.version + "\n"

        cls.count_issue_periods_and_act_on_it(issue, event, digested_at)

        issue.save()

        # intentionally at the end: possible future optimization is to push this out of the transaction (or even use
        # a separate DB for this)
        digest_tags(event_data, event, issue)

    @classmethod
    def count_project_periods_and_act_on_it(cls, project, now):
        # returns: True if any further processing should be done.

        thresholds = [
            ("minute", 5, get_settings().MAX_EVENTS_PER_PROJECT_PER_5_MINUTES),
            ("minute", 60, get_settings().MAX_EVENTS_PER_PROJECT_PER_HOUR),
        ]

        if project.quota_exceeded_until is not None and now < project.quota_exceeded_until:
            # This is the same check that we do on-ingest. Naively, one might think that it is superfluous. However,
            # because by design there is the potential for a digestion backlog to exist, it is possible that the update
            # of `project.quota_exceeded_until` happens only after any number of events have already passed through
            # ingestion and have entered the pipeline. Hence we double-check on-digest.

            # nothing to check (otherwise) or update on project in this case, also abort further event-processing
            return False

        project.digested_event_count += 1

        if project.digested_event_count >= project.next_quota_check:
            # check_for_thresholds is relatively expensive (SQL group by); we do it as little as possible

            # Notes on off-by-one:
            # * check_for_thresholds tests for "gte"; this means it will trigger once the quota is reached (not
            #   exceeded). We act accordingly by accepting this final event (returning True, count += 1) and closing the
            #   door (setting quota_exceeded_until).
            # * add_for_current=1 because we're called before the event is digested (it's not in Event.objects.filter),
            #   and because of the previous bullet we know that it will always be digested.
            states = check_for_thresholds(Event.objects.filter(project=project), now, thresholds, 1)

            until = max([below_from for (state, below_from, _, _) in states if state], default=None)

            # "at least 1" is a matter of taste; because the actual usage of `next_quota_check` is with a gte, leaving
            # it out would result in the same behavior. But once we reach this point we know that digested_event_count
            # will increase, so we know that a next check cannot happen before current + 1, we might as well be explicit
            check_again_after = max(1, min([check_after for (_, _, check_after, _) in states], default=1))

            project.quota_exceeded_until = until

            # note on correction of `digested_event_count += 1`: as long as we don't do that between the check on
            # next_quota_check (the if-statement) and the setting (the statement below) we're good.
            project.next_quota_check = project.digested_event_count + check_again_after

        project.save()
        return True

    @classmethod
    def count_issue_periods_and_act_on_it(cls, issue, event, timestamp):
        # See the project-version for various off-by-one notes (not reproduced here).
        #
        # We just have "unmute" as a purpose here, not "quota". I thought I'd have per-issue quota earlier (which would
        # ensure some kind of fairness within a project) but:
        #
        # * that doesn't quite work, because to determine the issue, you'd have to incur almost all of the digest cost.
        # * quota are expected to be set "high enough" anyway, i.e. only as a last line of defense against run-away
        #     clients
        # * "even if" you'd get this to work there'd be scenarios where it's useless, e.g. misbehaving groupers.
        thresholds = IssueStateManager.get_unmute_thresholds(issue)

        if thresholds and issue.digested_event_count >= issue.next_unmute_check:
            states = check_for_thresholds(Event.objects.filter(issue=issue), timestamp, thresholds)

            check_again_after = max(1, min([check_after for (_, _, check_after, _) in states], default=1))

            issue.next_unmute_check = issue.digested_event_count + check_again_after

            for (state, until, _, (period_name, nr_of_periods, gte_threshold)) in states:
                if not state:
                    continue

                IssueStateManager.unmute(issue, triggering_event=event, unmute_metadata={"mute_until": {
                    "period": period_name, "nr_of_periods": nr_of_periods, "volume": gte_threshold}})

                # In the (in the current UI impossible, and generally unlikely) case that multiple unmute conditions are
                # met simultaneously, we arbitrarily break after the first. (this makes it so that a single TurningPoint
                # is created and that the detail that there was also another reason to unmute doesn't show us, but
                # that's perfectly fine); it also matches what we do elsewhere (i.e. `IssueStateManager.unmute` where we
                # have `if is_muted`)
                break


class IngestEventAPIView(BaseIngestAPIView):

    def _post(self, request, project_pk=None):
        ingested_at = datetime.now(timezone.utc)
        project = self.get_project_for_request(project_pk, request)
        if project.quota_exceeded_until is not None and ingested_at < project.quota_exceeded_until:
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        # This endpoint is deprecated. Personally, I think it's the simpler (and given my goals therefore better) of the
        # two, but fighting windmills and all... given that it's deprecated, I'm not going to give it quite as much love
        # (at least for now). Interfaces between the internal methods quite changed a bit recently, and this one did not
        # keep up.
        #
        # In particular I'd like to just call process_event() here, but that takes both an event_id and an unparsed data
        # stream, and we don't have an event_id here before parsing (and we don't want to parse twice). similarly,
        # event_metadata construction requires the event_id.
        #
        # Instead, we just copy/pasted the relevant parts of process_event() here, and take only one branch (the one
        # that digests immediately); i.e. we always digest immediately, independent of the setting.

        event_data = json.loads(
            MaxDataReader("MAX_EVENT_SIZE", content_encoding_reader(
                MaxDataReader("MAX_EVENT_COMPRESSED_SIZE", request))).read())

        event_metadata = self.get_event_meta(event_data["event_id"], ingested_at, request, project)

        self.digest_event(event_metadata, event_data)

        return HttpResponse()


class IngestEnvelopeAPIView(BaseIngestAPIView):

    def _post(self, request, project_pk=None):
        ingested_at = datetime.now(timezone.utc)

        input_stream = MaxDataReader("MAX_ENVELOPE_SIZE", content_encoding_reader(
            MaxDataReader("MAX_ENVELOPE_COMPRESSED_SIZE", request)))

        # note: we use the unvalidated (against DSN) "project_pk"; b/c of the debug-nature we assume "not a problem"
        input_stream = StoreEnvelope(ingested_at, project_pk, input_stream) if get_settings().KEEP_ENVELOPES > 0 \
            else DontStoreEnvelope(input_stream)

        try:
            return self._post2(request, input_stream, ingested_at, project_pk)
        finally:
            # storing stuff in the DB on-ingest (rather than on digest-only) is not "as architected"; it's OK because
            # this is a debug-only thing.
            #
            # note: in finally, so this happens even for all paths, including errors and 404 (i.e. wrong DSN). By design
            # b/c the error-paths are often the interesting ones when debugging. We even store when over quota (429),
            # that's more of a trade-off to avoid adding extra complexity for a debug-tool.
            input_stream.store()

    def _post2(self, request, input_stream, ingested_at, project_pk=None):
        # Note: wrapping the COMPRESSES_SIZE checks arount request makes it so that when clients do not compress their
        # requests, they are still subject to the (smaller) maximums that apply pre-uncompress. This is exactly what we
        # want.
        parser = StreamingEnvelopeParser(input_stream)

        envelope_headers = parser.get_envelope_headers()

        # Getting the project is the only DB-touching (a read) we do before we (only in IMMEDIATE/EAGER modes), start
        # start read/writing in digest_event. Notes on transactions:
        #
        # * we could add `durable_atomic` here for explicitness / if we ever do more than one read (for consistent
        #   snapshots. As it stands, not needed. (I believe this is implicit due to Django or even sqlite itself)
        # * For the IMMEDIATE/EAGER cases we don't suffer from locks b/c sqlite upgrades read to write; I've tested this
        #   by adding sleep statements between the read/writes. I believe this is b/c of our immediate_atomic on
        #   digest_event. When removing that, and wrapping all of the present method in `durable_atomic`, read-write
        #   upgrades indeed fail.
        # * digest_event gets its own `project`, so there's no cross-transaction "pollution".
        # * Road not taken: pulling `immediate_atomic` up to the present level, but only for IMMEDIATE/EAGER modes (the
        #   only modes where this would make sense). This allows for passing of project between the 2 methods, but the
        #   added complexity (conditional transactions both here and in digest_event) is not worth it for modes that are
        #   non-production anyway.
        if "dsn" in envelope_headers:
            # as in get_sentry_key_for_request, we don't verify that the DSN contains the project_pk, for the same
            # reason ("reasons unconvincing")
            project = self.get_project(project_pk, get_sentry_key(envelope_headers["dsn"]))
        else:
            project = self.get_project_for_request(project_pk, request)

        if project.quota_exceeded_until is not None and ingested_at < project.quota_exceeded_until:
            # Sentry has x-sentry-rate-limits, but for now 429 is just fine. Client-side this is implemented as a 60s
            # backoff.
            #
            # Note "what's the use of this?": in my actual setups I have observed that we're almost entirely limited by
            # (nginx's) SSL processing on-ingest, and that digest is (almost) able to keep up. Because of request
            # buffering, the cost of such processing will already have been incurred once you reach this point. So is
            # the entire idea of quota useless? No, because the SDK will generally back off on 429, this does create
            # some relief. Also: avoid backlogging the digestion pipeline.
            #
            # Another aspect is: the quota serve as a first threshold for retention/evictions, i.e. some quota will mean
            # that retention is not too heavily favoring "most recent" when there are very many requests coming in.
            #
            # Note that events that exceed the quota will not be seen (not even counted) in any way; if we ever want to
            # do that we could make a specific task for it and delay that here (at a limited performance cost, but
            # keeping with the "don't block the main DB on-ingest" design)
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        def factory(item_headers):
            if item_headers.get("type") == "event":
                if get_settings().DIGEST_IMMEDIATELY:
                    return MaxDataWriter("MAX_EVENT_SIZE", io.BytesIO())

                # envelope_headers["event_id"] is required when type=event per the spec (and takes precedence over the
                # payload's event_id), so we can rely on it having been set.
                if "event_id" not in envelope_headers:
                    raise ParseError("event_id not found in envelope headers")
                filename = get_filename_for_event_id(envelope_headers["event_id"])
                os.makedirs(os.path.dirname(filename), exist_ok=True)
                return MaxDataWriter("MAX_EVENT_SIZE", open(filename, 'wb'))

            # everything else can be discarded; (we don't check for individual size limits, because these differ
            # per item type, we have the envelope limit to protect us, and we incur almost no cost (NullWriter) anyway.
            return NullWriter()

        for item_headers, event_output_stream in parser.get_items(factory):
            try:
                if item_headers.get("type") != "event":
                    logger.info("skipping non-event item: %s", item_headers.get("type"))

                    if item_headers.get("type") == "transaction":
                        # From the spec of type=event: This Item is mutually exclusive with `"transaction"` Items.
                        # i.e. when we see a transaction, a regular event will not be present and we can stop.
                        logger.info("discarding the rest of the envelope")
                        break

                    continue

                self.process_event(ingested_at, envelope_headers["event_id"], event_output_stream, project, request)
                break  # From the spec of type=event: This Item may occur at most once per Envelope. once seen: done

            finally:
                event_output_stream.close()

        return HttpResponse()


# Just a few thoughts on the relative performance of the main building blocks of dealing with Envelopes, and how this
# affect our decision making. On my local laptop (local loopback, django dev server), with a single 50KiB event, I
# measured the following approximate timtings:
# 0.00001s just get the bytes
# 0.0002s get bytes & gunzip
# 0.0005s get bytes, gunzip & json load
#
# The goal of having an ingest/digest split is to keep the server responsive in times of peek load. It is _not_ to have
# get crazy good throughput numbers (because ingest isn't the bottleneck anyway).
#
# One consideration was: should we just store the compressed envelope on-upload. Answer, given the numbers above: not
# needed, fine to unpack. This is also prudent from the perspective of storage, because the envelope may contain much
# more stuff that we don't care about (up to 20MiB compressed) whereas the max event size (uncompressed) is 1MiB.
# Another advantage: this allows us to raise the relevant Header parsing and size limitation Exceptions to the SDKs.
#


@user_passes_test(lambda u: u.is_superuser)
def download_envelope(request, envelope_id=None):
    envelope = get_object_or_404(Envelope, pk=envelope_id)
    response = HttpResponse(envelope.data, content_type="application/x-sentry-envelope")
    response["Content-Disposition"] = f'attachment; filename="envelope-{envelope_id}.envelope"'
    return response
