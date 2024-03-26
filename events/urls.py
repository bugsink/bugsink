from django.urls import path

from .views import event_download, debug_get_hash


urlpatterns = [
    # path('event/<uuid:pk>/', event_detail),  perhaps should become a redirect to issue/.../event now?
    path('event/<uuid:event_pk>/raw/', event_download, kwargs={"as_attachment": False}),
    path('event/<uuid:event_pk>/download/', event_download, kwargs={"as_attachment": True}),
    path('debug_get_hash/<uuid:event_pk>/', debug_get_hash),
]
