import json  # TODO consider faster APIs
from urllib.parse import urlparse

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import exceptions

# from projects.models import Project
from sentry.utils.auth import parse_auth_header

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
    def auth_from_request(cls, request):
        # VENDORED FROM GlitchTip at a4f33da8d4e759d61ffe073a00f2bb3839ac65f5
        # Accept both sentry or glitchtip prefix.
        for k in request.GET.keys():
            if k in ["sentry_key", "glitchtip_key"]:
                return request.GET[k]

        if auth_header := request.META.get(
            "HTTP_X_SENTRY_AUTH", request.META.get("HTTP_AUTHORIZATION")
        ):
            result = parse_auth_header(auth_header)
            return result.get("sentry_key", result.get("glitchtip_key"))

        if isinstance(request.data, list):
            if data_first := next(iter(request.data), None):
                if isinstance(data_first, dict):
                    dsn = urlparse(data_first.get("dsn"))
                    if username := dsn.username:
                        return username

        raise exceptions.NotAuthenticated("Unable to find authentication information")

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

    def post(self, request, *args, **kwargs):
        project = Project.objects.first()  # TODO actually parse project header
        self.process_event(request.data, request, project)
        return Response()


class IngestEnvelopeAPIView(BaseIngestAPIView):
    parser_classes = [EnvelopeParser]

    def post(self, request, *args, **kwargs):
        project = Project.objects.first()  # TODO actually parse project header

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
