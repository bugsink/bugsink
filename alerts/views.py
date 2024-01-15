from django.shortcuts import render

DEBUG_CONTEXTS = {
    "new_issue": {
    },
}


def debug_email(request, template_name):
    return render(request, 'alerts/' + template_name + ".html", DEBUG_CONTEXTS[template_name])
