from django.shortcuts import redirect
from django.conf import settings

from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_control
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import render

from projects.models import Project
from issues.views import issue_list


def home(request):
    if Project.objects.count() == 0:
        raise NotImplementedError("Onboarding not implemented yet")

    elif Project.objects.count() == 1:
        project = Project.objects.get()
        return redirect(issue_list, project_id=project.id)

    return render(request, "bugsink/home_project_list.html", {
        # user_projecs is in the context_processor, we don't need to pass it here
    })


def trigger_error(request):
    raise Exception("Exception triggered on purpose to debug error handling")


@require_GET
@cache_control(max_age=60 * 60 * 24, immutable=True, public=True)
def favicon(request: HttpRequest) -> HttpResponse:
    file = (settings.BASE_DIR / "static" / "favicon.png").open("rb")
    return FileResponse(file)
