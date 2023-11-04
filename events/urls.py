from django.urls import path

from .views import decompressed_event_detail, debug_get_hash


urlpatterns = [
    path('event/<uuid:pk>/', decompressed_event_detail),
    path('debug_get_hash/<uuid:decompressed_event_pk>/', debug_get_hash),
]
