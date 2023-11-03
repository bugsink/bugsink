from django.conf import settings

from django.contrib import admin
from django.urls import include, path

from .views import trigger_error


urlpatterns = [
    path('api/',  include('ingest.urls')),

    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += [
        path('trigger-error/', trigger_error),
    ]
