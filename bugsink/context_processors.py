from datetime import timedelta

from django.utils import timezone
from bugsink.app_settings import get_settings, CB_ANYBODY

from phonehome.models import Installation


def useful_settings_processor(request):
    installation = Installation.objects.get()

    nag_7 = installation.created_at < timezone.now() - timedelta(days=7)
    nag_30 = installation.created_at < timezone.now() - timedelta(days=30)

    return {
        # Note: no way to actually set the license key yet, so nagging always happens for now.
        'site_title': get_settings().SITE_TITLE + (" (non-production use)" if nag_7 else ""),
        'registration_enabled': get_settings().USER_REGISTRATION == CB_ANYBODY,
        'app_settings': get_settings(),

        # (First version of "should I nag" logic): nag only after considerable time to play with the app, and for "some
        # indication" that you're using this in production (the simplest such indication is that you've configured a
        # BASE_URL that's not localhost). Subject to change.
        'show_free_version_message': nag_30 and '127.0.0.1' not in get_settings().BASE_URL,
    }


def logged_in_user_processor(request):
    return {
        'logged_in_user': request.user,
    }
