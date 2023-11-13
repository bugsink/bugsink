from django.urls import path

from .views import event_detail, event_download, debug_get_hash


urlpatterns = [
    path('event/<uuid:pk>/', event_detail),
    path('event/<uuid:pk>/raw/', event_download, kwargs={"as_attachment": False}),
    path('event/<uuid:pk>/download/', event_download, kwargs={"as_attachment": True}),
    path('debug_get_hash/<uuid:event_pk>/', debug_get_hash),
]
