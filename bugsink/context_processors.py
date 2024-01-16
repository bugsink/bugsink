from django.conf import settings


def useful_settings_processor(request):
    return {
        'site_title': settings.SITE_TITLE,
    }
