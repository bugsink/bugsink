from django.shortcuts import render
from bugsink.app_settings import get_settings

DEBUG_CONTEXTS = {
    "issue_alert": {
        "site_title": get_settings().SITE_TITLE,
        "base_url": get_settings().BASE_URL + "/",
        "issue_title": "AttributeError: 'NoneType' object has no attribute 'data'",
        "project_name": "My first project",
        "alert_article": "a",
        "alert_reason": "NEW",
        "issue_url": get_settings().BASE_URL + "/issues/issue/00000000-0000-0000-0000-000000000000/",
        "settings_url": get_settings().BASE_URL + "/accounts/preferences/",
    },
}


def debug_email(request, template_name):
    return render(request, 'mails/' + template_name + ".html", DEBUG_CONTEXTS[template_name])
