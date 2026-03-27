from django.urls import path

from .views import IngestEventAPIView, IngestEnvelopeAPIView, MinidumpAPIView

urlpatterns = [
    # project_pk has to be an int per Sentry Client expectations.
    path("<int:project_pk>/store/", IngestEventAPIView.as_view(), name="ingest-store"),
    path("<int:project_pk>/envelope/", IngestEnvelopeAPIView.as_view(), name="ingest-envelope"),

    # is this "ingest"? it is at least in the sense that it matches the API schema and downstream auth etc.
    path("<int:project_pk>/minidump/", MinidumpAPIView.as_view(), name="ingest-minidump"),
]
