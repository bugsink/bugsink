import json  # TODO consider faster APIs
from urllib.parse import urlparse

from django.shortcuts import get_object_or_404

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import exceptions

# from projects.models import Project
from sentry.utils.auth import parse_auth_header

from bugsink.exceptions import ViolatedExpectation
from projects.models import Project
from issues.models import Issue
from issues.utils import get_hash_for_data


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
        # VENDORED FROM GlitchTip at a4f33da8d4e759d61ffe073a00f2bb3839ac65f5, with changes

        # KvS: I have not been able to find documentation which suggests that the below is indeed used.
        if "sentry_key" in request.GET:
            raise ViolatedExpectation("sentry_key in request.GET is indeed used. Turn on this code.")
            return request.GET["sentry_key"]

        # KvS: parsing using HTTP headers. I'm not sure which of the headers is the "standard" in sentry-client land.
        for auth_key in ["HTTP_X_SENTRY_AUTH", "HTTP_AUTHORIZATION"]:
            if auth_key in request.META:
                auth_dict = parse_auth_header(request.META[auth_key])
                return auth_dict.get("sentry_key")

        # KvS: this is presumably the path that is used for envelopes (and then also when the above are not provided)
        if isinstance(request.data, list):
            if data_first := next(iter(request.data), None):
                if isinstance(data_first, dict):
                    dsn = urlparse(data_first.get("dsn"))
                    if dsn.username:
                        return dsn.username

        raise exceptions.NotAuthenticated("Unable to find authentication information")

    @classmethod
    def get_project(cls, request, project_id):
        # NOTE this gives a 404 for non-properly authorized. Is this really something we care about, i.e. do we want to
        # raise NotAuthenticated? In that case we need to get the project first, and then do a constant-time-comp on the
        # sentry_key
        sentry_key = cls.get_sentry_key_for_request(request)
        return get_object_or_404(Project, pk=project_id, sentry_key=sentry_key)

    def process_event(self, event_data, request, project):
        event = DecompressedEvent.objects.create(
            project=project,
            data=json.dumps(event_data),  # TODO don't parse-then-print for BaseIngestion
        )

        hash_ = get_hash_for_data(event_data)

        issue, _ = Issue.objects.get_or_create(
            hash=hash_,
        )
        issue.events.add(event)


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

        event = request.data[2]
        self.process_event(event, request, project)
        return Response()
