from django.shortcuts import render
from django.conf import settings

DEBUG_CONTEXTS = {
    "issue_alert": {
        "site_name": settings.SITE_NAME,
        "base_url": settings.BASE_URL + "/",
        "issue_title": "AttributeError: 'NoneType' object has no attribute 'data'",
        "project_name": "My first project",
        "alert_article": "a",
        "alert_reason": "NEW",
        "issue_url": settings.BASE_URL + "/issues/issue/00000000-0000-0000-0000-000000000000/",
        "settings_url": settings.BASE_URL + "/",  # TODO
    },
}


def debug_email(request, template_name):
    return render(request, 'alerts/' + template_name + ".html", DEBUG_CONTEXTS[template_name])
