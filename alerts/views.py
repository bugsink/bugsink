from django.shortcuts import render
from django.conf import settings

DEBUG_CONTEXTS = {
    "new_issue": {
        "base_url": settings.BASE_URL + "/",
        "issue_title": "AttributeError: 'NoneType' object has no attribute 'data'",
        "project_name": "My first project",
        "issue_url": settings.BASE_URL + "/issues/issue/00000000-0000-0000-0000-000000000000/",
    },
}


def debug_email(request, template_name):
    return render(request, 'alerts/' + template_name + ".html", DEBUG_CONTEXTS[template_name])
