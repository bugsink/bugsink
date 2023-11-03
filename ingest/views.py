from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

# from projects.models import Project
# from sentry.utils.auth import parse_auth_header

from .negotiation import IgnoreClientContentNegotiation
from .parsers import EnvelopeParser


class BaseIngestAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    content_negotiation_class = IgnoreClientContentNegotiation
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        import pdb; pdb.set_trace()
        # return self.process_event(request.data, request, project)
        return Response()


class IngestEventAPIView(BaseIngestAPIView):
    pass


class IngestEnvelopeAPIView(BaseIngestAPIView):
    parser_classes = [EnvelopeParser]
