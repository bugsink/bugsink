from django.conf import settings

from django.contrib import admin
from django.urls import include, path

from .views import home, trigger_error, favicon
from alerts.views import debug_email


urlpatterns = [
    path('', home),

    path('api/', include('ingest.urls')),

    path('events/', include('events.urls')),
    path('issues/', include('issues.urls')),

    path('admin/', admin.site.urls),

    path("favicon.ico", favicon),
]

if settings.DEBUG:
    urlpatterns += [
        path('debug-email-alerts/<str:template_name>/', debug_email),
        path('trigger-error/', trigger_error),
    ]
