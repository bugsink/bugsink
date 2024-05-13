from bugsink.app_settings import get_settings


def useful_settings_processor(request):
    return {
        'site_title': get_settings().SITE_TITLE,
    }


def logged_in_user_processor(request):
    return {
        'logged_in_user': request.user,
    }
