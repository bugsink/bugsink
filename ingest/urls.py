from django.urls import path

from .views import IngestEventAPIView, IngestEnvelopeAPIView

urlpatterns = [
    # project_pk has to be an int per Sentry Client expectations.
    path("<int:project_pk>/store/", IngestEventAPIView.as_view()),
    path("<int:project_pk>/envelope/", IngestEnvelopeAPIView.as_view()),
]
