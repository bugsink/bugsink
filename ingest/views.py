from datetime import datetime, timezone
import json  # TODO consider faster APIs

from django.shortcuts import get_object_or_404
from django.conf import settings
from django.db.models import Max

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import exceptions
from rest_framework.exceptions import ValidationError

# from projects.models import Project
from compat.auth import parse_auth_header_value

from projects.models import Project
from issues.models import Issue, IssueStateManager, Grouping
from issues.utils import get_type_and_value_for_data, get_issue_grouper_for_data, get_denormalized_fields_for_data
from issues.regressions import issue_is_regression

import sentry_sdk_extensions
from events.models import Event
from releases.models import create_release_if_needed
from bugsink.registry import get_pc_registry
from bugsink.period_counter import PeriodCounter
from alerts.tasks import send_new_issue_alert, send_regression_alert
from bugsink.exceptions import ViolatedExpectation

from .negotiation import IgnoreClientContentNegotiation
from .parsers import EnvelopeParser
from .models import DecompressedEvent


class BaseIngestAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    content_negotiation_class = IgnoreClientContentNegotiation
    http_method_names = ["post"]

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
        project_pc.inc(now)

        debug_info = request.META.get("HTTP_X_BUGSINK_DEBUGINFO", "")

        return DecompressedEvent.objects.create(
            project=project,
            data=json.dumps(event_data),  # TODO don't parse-then-print for BaseIngestion
            timestamp=now,
            debug_info=debug_info,
        )

    @classmethod
    def digest_event(cls, ingested_event, event_data):
        # event_data is passed explicitly to avoid re-parsing something that may be availabe anyway; we'll come up with
        # a better signature later if this idea sticks

        # leave this at the top -- it may involve reading from the DB which should come before any DB writing
        pc_registry = get_pc_registry()

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

        create_release_if_needed(ingested_event.project, event.release)

        if issue_created:
            if ingested_event.project.alert_on_new_issue:
                send_new_issue_alert.delay(issue.id)

        else:
            # new issues cannot be regressions by definition, hence this is in the 'else' branch
            if issue_is_regression(issue, event.release):
                if ingested_event.project.alert_on_regression:
                    send_regression_alert.delay(issue.id)

                IssueStateManager.reopen(issue)

            # note that while digesting we _only_ care about .is_muted to determine whether unmuting (and alerting about
            # unmuting) should happen, whether as a result of a VBC or 'after time'. Somewhat counter-intuitively, a
            # 'muted' issue is thus not treated as something to more deeply ignore than an unresolved issue (and in
            # fact, conversely, it may be more loud when the for/until condition runs out). This is in fact analogous to
            # "resolved" issues which are _also_ treated with more "suspicion" than their unresolved counterparts.
            if issue.is_muted and issue.unmute_after is not None and ingested_event.timestamp > issue.unmute_after:
                # note that unmuting on-ingest implies that issues that no longer occur stay muted. I'd say this is what
                # you want: things that no longer happen should _not_ draw your attention, and if you've nicely moved
                # some issue away from the "Open" tab it should not reappear there if a certain amount of time happens.
                # Thus, unmute_after should more completely be called unmute_until_events_happen_after but that's a bit
                # long. Phrased slightly differently: you basically click the button saying "I suppose this issue will
                # self-resolve in x time; notify me if this is not the case"
                IssueStateManager.unmute(issue, triggered_by_event=True)

            # update the denormalized fields
            issue.last_seen = ingested_event.timestamp
            issue.event_count += 1

        if issue.id not in get_pc_registry().by_issue:
            pc_registry.by_issue[issue.id] = PeriodCounter()
        issue_pc = get_pc_registry().by_issue[issue.id]
        issue_pc.inc(ingested_event.timestamp)

        # TODO bookkeeping of events_at goes here.
        issue.save()


class IngestEventAPIView(BaseIngestAPIView):

    def post(self, request, project_pk=None):
        project = self.get_project(request, project_pk)

        self.process_event(request.data, project, request)
        return Response()


class IngestEnvelopeAPIView(BaseIngestAPIView):
    parser_classes = [EnvelopeParser]

    def post(self, request, project_pk=None):
        project = self.get_project(request, project_pk)

        data = request.data  # make this a local var to ensure it's sent as part of capture_stacktrace(..)
        if len(data) < 3:
            # we expect at least a header, a type-decla, and a body; this enables us to deal with a good number of
            # messages, however, a proper implementation of Envelope parsing, including parsing of the headers and the
            # body (esp. if there multiple parts), using both the specification (if there is any) and the sentry
            # codebase as a reference, is a TODO (such extra parts are currently silently ignored)
            sentry_sdk_extensions.capture_stacktrace("Invalid envelope (< 3 parts)")
            return Response({"message": "Missing headers / unsupported type"}, status=status.HTTP_501_NOT_IMPLEMENTED)

        if len(data) > 3:
            sentry_sdk_extensions.capture_stacktrace("> 3 envelope parts, logged for understanding")  # i.e. no error

        if data[1].get("type") != "event":
            sentry_sdk_extensions.capture_stacktrace("Invalid envelope (not an event)")
            return Response({"message": "Only events are supported"}, status=status.HTTP_501_NOT_IMPLEMENTED)

        # TODO think about a good order to handle this in. Namely: if no project Header is provided, you are basically
        # forced to do some parsing of the envelope... and this could be costly.
        # https://gitlab.com/glitchtip/glitchtip-backend/-/issues/181

        """
        # KvS: this is presumably the path that is used for envelopes (and then also when the above are not provided)
        # TODO I'd much rather deal with that explicitly
        from urllib.parse import urlparse
        if isinstance(data, list):
            if data_first := next(iter(data), None):
                if isinstance(data_first, dict):
                    dsn = urlparse(data_first.get("dsn"))
                    if dsn.username:
                        return dsn.username
        """

        event = data[2]
        self.process_event(event, project, request)
        return Response()
