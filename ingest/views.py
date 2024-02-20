from datetime import datetime, timezone
import json  # TODO consider faster APIs

from django.shortcuts import get_object_or_404
from django.conf import settings

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import exceptions

# from projects.models import Project
from compat.auth import parse_auth_header_value

from projects.models import Project
from issues.models import Issue, IssueStateManager
from issues.utils import get_hash_for_data
from issues.regressions import issue_is_regression

import sentry_sdk_extensions
from events.models import Event
from releases.models import create_release_if_needed
from bugsink.registry import get_pc_registry
from bugsink.period_counter import PeriodCounter
from alerts.tasks import send_new_issue_alert, send_regression_alert


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
    def get_project(cls, request, project_id):
        # NOTE this gives a 404 for non-properly authorized. Is this really something we care about, i.e. do we want to
        # raise NotAuthenticated? In that case we need to get the project first, and then do a constant-time-comp on the
        # sentry_key
        sentry_key = cls.get_sentry_key_for_request(request)
        return get_object_or_404(Project, pk=project_id, sentry_key=sentry_key)

    @classmethod
    def process_event(cls, event_data, project, request):
        # because we want to count events before having created event objects (quota may block the latter) we cannot
        # depend on event.timestamp; instead, we look on the clock once here, and then use that for both the project
        # and issue period counters.
        now = datetime.now(timezone.utc)

        # note: we may want to skip saving the raw data in a setup where we have integrated ingest/digest, but for now
        # we just always save it; note that even for the integrated setup a case can be made for saving the raw data
        # before proceeding because it may be useful for debugging errors in the digest process.
        ingested_event = cls.ingest_event(now, event_data, request, project)
        if settings.BUGSINK_DIGEST_IMMEDIATELY:
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

        hash_ = get_hash_for_data(event_data)
        issue, issue_created = Issue.objects.get_or_create(
            project=ingested_event.project,
            hash=hash_,
            defaults={
                "first_seen": ingested_event.timestamp,
                "last_seen": ingested_event.timestamp,
                "event_count": 1,
            },
        )

        event, event_created = Event.from_ingested(ingested_event, issue, event_data)
        if not event_created:
            # note: previously we created the event before the issue, which allowed for one less query. I don't see
            # straight away how we can reproduce that now that we create issue-before-event (since creating the issue
            # first is needed to be able to set the FK in one go)
            return

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

    def post(self, request, project_id=None):
        project = self.get_project(request, project_id)

        self.process_event(request.data, project, request)
        return Response()


class IngestEnvelopeAPIView(BaseIngestAPIView):
    parser_classes = [EnvelopeParser]

    def post(self, request, project_id=None):
        project = self.get_project(request, project_id)

        if len(request.data) != 3:
            # multi-part envelopes trigger an error too
            sentry_sdk_extensions.capture_stacktrace("Invalid envelope (not 3 parts)")
            return Response({"message": "Missing headers / unsupported type"}, status=status.HTTP_501_NOT_IMPLEMENTED)

        if request.data[1].get("type") != "event":
            sentry_sdk_extensions.capture_stacktrace("Invalid envelope (not an event)")
            return Response({"message": "Only events are supported"}, status=status.HTTP_501_NOT_IMPLEMENTED)

        # TODO think about a good order to handle this in. Namely: if no project Header is provided, you are basically
        # forced to do some parsing of the envelope... and this could be costly.
        # https://gitlab.com/glitchtip/glitchtip-backend/-/issues/181

        """
        # KvS: this is presumably the path that is used for envelopes (and then also when the above are not provided)
        # TODO I'd much rather deal with that explicitly
        from urllib.parse import urlparse
        if isinstance(request.data, list):
            if data_first := next(iter(request.data), None):
                if isinstance(data_first, dict):
                    dsn = urlparse(data_first.get("dsn"))
                    if dsn.username:
                        return dsn.username
        """

        event = request.data[2]
        self.process_event(event, project, request)
        return Response()
