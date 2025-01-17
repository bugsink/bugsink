from django.conf import settings

from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views

from alerts.views import debug_email as debug_alerts_email
from users.views import debug_email as debug_users_email
from teams.views import debug_email as debug_teams_email
from bugsink.app_settings import get_settings
from users.views import signup, confirm_email, resend_confirmation, request_reset_password, reset_password, preferences
from ingest.views import download_envelope

from .views import home, trigger_error, favicon, settings_view, silence_email_system_warning
from .debug_views import csrf_debug


admin.site.site_header = get_settings().SITE_TITLE
admin.site.site_title = get_settings().SITE_TITLE
admin.site.index_title = "Admin"  # everyone calls this the "admin" anyway. Let's set the title accordingly.


urlpatterns = [
    path('', home, name='home'),

    path("accounts/signup/", signup, name="signup"),
    path("accounts/resend-confirmation/", resend_confirmation, name="resend_confirmation"),
    path("accounts/confirm-email/<str:token>/", confirm_email, name="confirm_email"),

    path("accounts/request-reset-password/", request_reset_password, name="request_reset_password"),
    path("accounts/reset-password/<str:token>/", reset_password, name="reset_password"),

    path("accounts/login/", auth_views.LoginView.as_view(template_name="bugsink/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(template_name="users/logged_out.html"), name="logout"),

    path("accounts/preferences/", preferences, name="preferences"),

    # many user-related views are directly exposed above (/accounts/), the rest is here:
    path("users/", include("users.urls")),

    path('api/', include('ingest.urls')),

    # not in /api/ because it's not part of the ingest API, but still part of the ingest app
    path('ingest/envelope/<str:envelope_id>/', download_envelope, name='download_envelope'),

    path('projects/', include('projects.urls')),
    path('teams/', include('teams.urls')),
    path('events/', include('events.urls')),
    path('issues/', include('issues.urls')),

    path('admin/', admin.site.urls),

    path('silence-email-system-warning/', silence_email_system_warning, name='silence_email_system_warning'),
    path('settings/', settings_view, name='settings'),
    path('debug/csrf/', csrf_debug, name='csrf_debug'),

    path("favicon.ico", favicon),
]

if settings.DEBUG:
    urlpatterns += [
        path('debug-alerts-email/<str:template_name>/', debug_alerts_email),
        path('debug-users-email/<str:template_name>/', debug_users_email),
        path('debug-teams-email/<str:template_name>/', debug_teams_email),
        path('trigger-error/', trigger_error),
        path("__debug__/", include("debug_toolbar.urls")),
    ]


handler400 = "bugsink.views.bad_request"
handler403 = "bugsink.views.permission_denied"
handler404 = "bugsink.views.page_not_found"
handler500 = "bugsink.views.server_error"
