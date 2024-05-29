from bugsink.app_settings import get_settings, CB_ANYBODY


def useful_settings_processor(request):
    return {
        'site_title': get_settings().SITE_TITLE,
        'registration_enabled': get_settings().USER_REGISTRATION == CB_ANYBODY,
    }


def logged_in_user_processor(request):
    return {
        'logged_in_user': request.user,
    }
