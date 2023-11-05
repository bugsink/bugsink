import json  # TODO consider faster APIs

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

# from projects.models import Project
# from sentry.utils.auth import parse_auth_header

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
