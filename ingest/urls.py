from django.urls import path

from .views import IngestEventAPIView, IngestEnvelopeAPIView, MinidumpAPIView, IngestSecurityAPIView

urlpatterns = [
    # project_pk has to be an int per Sentry Client expectations.
    path("<int:project_pk>/store/", IngestEventAPIView.as_view(), name="ingest-store"),
    path("<int:project_pk>/envelope/", IngestEnvelopeAPIView.as_view(), name="ingest-envelope"),

    # is this "ingest"? it is at least in the sense that it matches the API schema and downstream auth etc.
    path("<int:project_pk>/minidump/", MinidumpAPIView.as_view(), name="ingest-minidump"),

    # Browser-emitted CSP violation reports (report-uri directive). Auth via ?sentry_key= query param because browsers
    # cannot set custom headers on CSP report POSTs.
    path("<int:project_pk>/security/", IngestSecurityAPIView.as_view(), name="ingest-security"),
]
