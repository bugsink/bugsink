import json  # TODO consider faster APIs

from django.shortcuts import get_object_or_404

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import exceptions

# from projects.models import Project
from compat.auth import parse_auth_header_value

from projects.models import Project
from issues.models import Issue
from issues.utils import get_hash_for_data
from issues.regressions import event_is_regression

from events.models import Event
from releases.models import Release

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

    def process_event(self, event_data, request, project):
        DecompressedEvent.objects.create(
            project=project,
            data=json.dumps(event_data),  # TODO don't parse-then-print for BaseIngestion
        )

        debug_info = request.META.get("HTTP_X_BUGSINK_DEBUGINFO", "")

        event, event_created = Event.from_json(project, event_data, debug_info)
        if not event_created:
            return

        # NOTE: we even create a Release for the empty release here; we need the associated info (date_released) if a
        # real release is ever created later.
        release, release_created = Release.objects.get_or_create(project=project, version=event.release)
        if release_created and event.release != "":
            if not project.has_releases:
                project.has_releases = True
                project.save()

            if release == project.get_latest_release():
                for bnr_issue in Issue.objects.filter(project=project, is_resolved_by_next_release=True):
                    bnr_issue.add_fixed_at(release)
                    bnr_issue.is_resolved_by_next_release = False
                    bnr_issue.save()

        hash_ = get_hash_for_data(event_data)

        issue, issue_created = Issue.objects.get_or_create(
            project=project,
            hash=hash_,
        )
        issue.events.add(event)

        if issue_created:
            pass  # alerting code goes here

        elif event_is_regression(event):  # new issues cannot be regressions by definition, hence the 'else'
            pass  # alerting code goes here
            issue.is_resolved = False

        # TODO bookkeeping of events_at goes here.


class IngestEventAPIView(BaseIngestAPIView):

    def post(self, request, project_id=None):
        project = self.get_project(request, project_id)

        self.process_event(request.data, request, project)
        return Response()


class IngestEnvelopeAPIView(BaseIngestAPIView):
    parser_classes = [EnvelopeParser]

    def post(self, request, project_id=None):
        project = self.get_project(request, project_id)

        if len(request.data) != 3:
            # multi-part envelopes trigger an error too
            print("!= 3")
            return Response({"message": "Missing headers / unsupported type"}, status=status.HTTP_501_NOT_IMPLEMENTED)

        if request.data[1].get("type") != "event":
            print("!= event")
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
        self.process_event(event, request, project)
        return Response()
