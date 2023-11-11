from django.urls import path

from .views import event_detail, debug_get_hash


urlpatterns = [
    path('event/<uuid:pk>/', event_detail),
    path('debug_get_hash/<uuid:event_pk>/', debug_get_hash),
]
