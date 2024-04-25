import logging
import io
from datetime import datetime, timezone
import json  # TODO consider faster APIs

from django.shortcuts import get_object_or_404
from django.conf import settings
from django.db.models import Max
from django.views import View
from django.core import exceptions
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from compat.auth import parse_auth_header_value

from projects.models import Project
from issues.models import Issue, IssueStateManager, Grouping, TurningPoint, TurningPointKind
from issues.utils import get_type_and_value_for_data, get_issue_grouper_for_data, get_denormalized_fields_for_data
from issues.regressions import issue_is_regression

from bugsink.registry import get_pc_registry
from bugsink.period_counter import PeriodCounter
from bugsink.transaction import immediate_atomic, delay_on_commit
from bugsink.exceptions import ViolatedExpectation
from bugsink.streams import content_encoding_reader

from events.models import Event
from releases.models import create_release_if_needed
from alerts.tasks import send_new_issue_alert, send_regression_alert

from .parsers import StreamingEnvelopeParser
from .models import DecompressedEvent


HTTP_400_BAD_REQUEST = 400
HTTP_501_NOT_IMPLEMENTED = 501


logger = logging.getLogger("bugsink.ingest")


@method_decorator(csrf_exempt, name='dispatch')
class BaseIngestAPIView(View):

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

        raise exceptions.NotAuthenticated("Unable to find authentication information")

    @classmethod
    def get_project(cls, request, project_pk):
        # NOTE this gives a 404 for non-properly authorized. Is this really something we care about, i.e. do we want to
        # raise NotAuthenticated? In that case we need to get the project first, and then do a constant-time-comp on the
        # sentry_key
        sentry_key = cls.get_sentry_key_for_request(request)
        return get_object_or_404(Project, pk=project_pk, sentry_key=sentry_key)

    @classmethod
    def process_event(cls, event_data, project, request, now=None):
        if now is None:  # now is not-None in tests
            # because we want to count events before having created event objects (quota may block the latter) we cannot
            # depend on event.timestamp; instead, we look on the clock once here, and then use that for both the project
            # and issue period counters.
            now = datetime.now(timezone.utc)

        # note: we may want to skip saving the raw data in a setup where we have integrated ingest/digest, but for now
        # we just always save it; note that even for the integrated setup a case can be made for saving the raw data
        # before proceeding because it may be useful for debugging errors in the digest process.
        ingested_event = cls.ingest_event(now, event_data, request, project)
        if settings.BUGSINK_DIGEST_IMMEDIATELY:
            # NOTE once we implement the no-immediate case, we should do so in a way that catches ValidationErrors
            # raised by digest_event
            cls.digest_event(ingested_event, event_data)

    @classmethod
    def ingest_event(cls, now, event_data, request, project):
        # JIT-creation of the PeriodCounter for the project; alternatively we could monitor the project creation and
        # create the PeriodCounter there.
        if project.id not in get_pc_registry().by_project:
            get_pc_registry().by_project[project.id] = PeriodCounter()

        project_pc = get_pc_registry().by_project[project.id]
        project_pc.inc(now)  # counted_entity (event) is not available yet, since we don't use it we don't pass it.

        debug_info = request.META.get("HTTP_X_BUGSINK_DEBUGINFO", "")

        return DecompressedEvent.objects.create(
            project=project,
            data=json.dumps(event_data),  # TODO don't parse-then-print for BaseIngestion
            timestamp=now,
            debug_info=debug_info,
        )

    @classmethod
    def digest_event(cls, ingested_event, event_data):
        event, issue = cls._digest_event_to_db(ingested_event, event_data)
        cls._digest_event_python_postprocessing(ingested_event, event, issue)

    @classmethod
    @immediate_atomic()
    def _digest_event_to_db(cls, ingested_event, event_data):
        # event_data is passed explicitly to avoid re-parsing something that may be availabe anyway; we'll come up with
        # a better signature later if this idea sticks

        # leave this at the top -- the point is to trigger load_from_scratch if needed, which may involve reading from
        # the DB which should come before any DB writing
        get_pc_registry()

        # I resisted the temptation to put `get_denormalized_fields_for_data` in an if-statement: you basically "always"
        # need this info... except when duplicate event-ids are sent. But the latter is the exception, and putting this
        # in an if-statement would require more rework (and possibly extra queries) than it's worth.
        denormalized_fields = get_denormalized_fields_for_data(event_data)
        # the 3 lines below are suggestive of a further inlining of the get_type_and_value_for_data function
        calculated_type, calculated_value = get_type_and_value_for_data(event_data)
        denormalized_fields["calculated_type"] = calculated_type
        denormalized_fields["calculated_value"] = calculated_value

        grouping_key = get_issue_grouper_for_data(event_data, calculated_type, calculated_value)

        if not Grouping.objects.filter(project=ingested_event.project, grouping_key=grouping_key).exists():
            # we don't have Project.issue_count here ('premature optimization') so we just do an aggregate instead.
            max_current = Issue.objects.filter(project=ingested_event.project).aggregate(
                Max("ingest_order"))["ingest_order__max"]
            issue_ingest_order = max_current + 1 if max_current is not None else 1

            issue = Issue.objects.create(
                ingest_order=issue_ingest_order,
                project=ingested_event.project,
                first_seen=ingested_event.timestamp,
                last_seen=ingested_event.timestamp,
                event_count=1,
                **denormalized_fields,
            )
            # even though in our data-model a given grouping does not imply a single Issue (in fact, that's the whole
            # point of groupings as a data-model), at-creation such implication does exist, because manual information
            # ("this grouper is actually part of some other issue") can by definition not yet have been specified.
            issue_created = True

            grouping = Grouping.objects.create(
                project=ingested_event.project,
                grouping_key=grouping_key,
                issue=issue,
            )

        else:
            grouping = Grouping.objects.get(project=ingested_event.project, grouping_key=grouping_key)
            issue = grouping.issue
            issue_created = False

        # NOTE: an event always has a single (automatically calculated) Grouping associated with it. Since we have that
        # information available here, we could add it to the Event model.
        event, event_created = Event.from_ingested(
            ingested_event,
            # the assymetry with + 1 is because the event_count is only incremented below for the not issue_created case
            issue.event_count if issue_created else issue.event_count + 1,
            issue,
            event_data,
            denormalized_fields,
        )
        if not event_created:
            # note: previously we created the event before the issue, which allowed for one less query. I don't see
            # straight away how we can reproduce that now that we create issue-before-event (since creating the issue
            # first is needed to be able to set the FK in one go)

            if issue_created:
                # this is a weird case that "should not happen" (but can happen in practice). Namely, when some client
                # sends events with the same event_id (leading to no new event), but different-enough actual data that
                # they lead to new issue-creation. I've already run into this while debugging (and this may in fact be
                # the only realistic scenario): manually editing some sample event but not updating the event_id (nor
                # running send_json with --fresh-id). We raise an exception after cleaning up, to at least avoid getting
                # into an inconsistent state in the DB.
                issue.delete()
                raise ViolatedExpectation("no event created, but issue created")

            # Validating by letting the DB raise an exception, and only after taking some other actions already, is not
            # "by the book" (some book), but it's the most efficient way of doing it when your basic expectation is that
            # multiple events with the same event_id "don't happen" (i.e. are the result of badly misbehaving clients)
            raise ValidationError("Event already exists", code="event_already_exists")

        release = create_release_if_needed(ingested_event.project, event.release, event)

        if issue_created:
            TurningPoint.objects.create(
                issue=issue, triggering_event=event, timestamp=ingested_event.timestamp,
                kind=TurningPointKind.FIRST_SEEN)

            if ingested_event.project.alert_on_new_issue:
                delay_on_commit(send_new_issue_alert, str(issue.id))

        else:
            # new issues cannot be regressions by definition, hence this is in the 'else' branch
            if issue_is_regression(issue, event.release):
                TurningPoint.objects.create(
                    issue=issue, triggering_event=event, timestamp=ingested_event.timestamp,
                    kind=TurningPointKind.REGRESSED)

                if ingested_event.project.alert_on_regression:
                    delay_on_commit(send_regression_alert, str(issue.id))

                IssueStateManager.reopen(issue)

            # note that while digesting we _only_ care about .is_muted to determine whether unmuting (and alerting about
            # unmuting) should happen, whether as a result of a VBC or 'after time'. Somewhat counter-intuitively, a
            # 'muted' issue is thus not treated as something to more deeply ignore than an unresolved issue (and in
            # fact, conversely, it may be more loud when the for/until condition runs out). This is in fact analogous to
            # "resolved" issues which are _also_ treated with more "suspicion" than their unresolved counterparts.
            if issue.is_muted and issue.unmute_after is not None and ingested_event.timestamp > issue.unmute_after:
                # note that unmuting on-ingest implies that issues that no longer occur stay muted. I'd say this is what
                # you want: things that no longer happen should _not_ draw your attention, and if you've nicely moved
                # some issue away from the "Open" tab it should not reappear there if a certain amount of time passes.
                # Thus, unmute_after should more completely be called unmute_until_events_happen_after but that's a bit
                # long. Phrased slightly differently: you basically click the button saying "I suppose this issue will
                # self-resolve in x time; notify me if this is not the case"
                IssueStateManager.unmute(
                    issue, triggering_event=event,
                    unmute_metadata={"mute_for": {"unmute_after": issue.unmute_after}})

            # update the denormalized fields
            issue.last_seen = ingested_event.timestamp
            issue.event_count += 1

        if release.version + "\n" not in issue.events_at:
            issue.events_at += release.version + "\n"
        issue.save()
        return event, issue

    @classmethod
    def _digest_event_python_postprocessing(cls, ingested_event, event, issue):
        pc_registry = get_pc_registry()
        if issue.id not in pc_registry.by_issue:
            pc_registry.by_issue[issue.id] = PeriodCounter()
        issue_pc = pc_registry.by_issue[issue.id]
        issue_pc.inc(ingested_event.timestamp, counted_entity=event)


class IngestEventAPIView(BaseIngestAPIView):

    def post(self, request, project_pk=None):
        project = self.get_project(request, project_pk)

        request_data = json.loads(content_encoding_reader(request).read())

        try:
            self.process_event(request_data, project, request)
        except exceptions.ValidationError as e:
            return JsonResponse({"message": str(e)}, status=HTTP_400_BAD_REQUEST)  # NOTE untested behavior

        return HttpResponse()


class IngestEnvelopeAPIView(BaseIngestAPIView):

    def post(self, request, project_pk=None):
        project = self.get_project(request, project_pk)

        parser = StreamingEnvelopeParser(content_encoding_reader(request))

        # TODO: use the envelope_header's DSN if it is available (exact order-of-operations will depend on load-shedding
        # mechanisms)
        # envelope_headers = parser.get_envelope_headers()
        # envelope_headers["event_id"] is required when type=event per the spec (and takes precedence over the payload's
        # event_id), so we can relay on it having been set.

        for item_headers, output_stream in parser.get_items(lambda item_headers: io.BytesIO()):
            try:
                item_bytes = output_stream.getvalue()
                if item_headers.get("type") != "event":
                    logger.info("skipping non-event item: %s", item_headers.get("type"))

                    if item_headers.get("type") == "transaction":
                        # From the spec of type=event: This Item is mutually exclusive with `"transaction"` Items.
                        # i.e. when we see a transaction, a regular event will not be present and we can stop.
                        logger.info("discarding the rest of the envelope")
                        break

                    continue

                event_data = json.loads(item_bytes.decode("utf-8"))

                self.process_event(event_data, project, request)
                break  # From the spec of type=event: This Item may occur at most once per Envelope. i.e. seen=done

            finally:
                output_stream.close()

        return HttpResponse()
