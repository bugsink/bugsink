from django.urls import path

from .views import IngestEventAPIView, IngestEnvelopeAPIView

urlpatterns = [
    # project_id has to be an int per Sentry Client expectations.
    path("<int:project_id>/store/", IngestEventAPIView.as_view()),
    path("<int:project_id>/envelope/", IngestEnvelopeAPIView.as_view()),
]
