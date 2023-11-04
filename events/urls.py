from django.urls import path

from .views import decompressed_event_detail


urlpatterns = [
    path('event/<uuid:pk>/', decompressed_event_detail),
]
