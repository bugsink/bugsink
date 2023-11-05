from django.conf import settings

from django.contrib import admin
from django.urls import include, path

from .views import trigger_error, favicon


urlpatterns = [
    path('api/', include('ingest.urls')),

    path('events/', include('events.urls')),
    path('issues/', include('issues.urls')),

    path('admin/', admin.site.urls),

    path("favicon.ico", favicon),
]

if settings.DEBUG:
    urlpatterns += [
        path('trigger-error/', trigger_error),
    ]
