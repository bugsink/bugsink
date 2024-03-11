from django.shortcuts import redirect
from django.conf import settings

from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_control
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import render

from bugsink.decorators import login_exempt


def home(request):
    project_count = request.user.project_set.all().count()

    if project_count == 0:
        raise NotImplementedError("Onboarding not implemented yet")

    elif project_count == 1:
        project = request.user.project_set.get()
        return redirect("issue_list_open", project_id=project.id)

    return render(request, "bugsink/home_project_list.html", {
        # user_projecs is in the context_processor, we don't need to pass it here
    })


@login_exempt
def trigger_error(request):
    raise Exception("Exception triggered on purpose to debug error handling")


@require_GET
@cache_control(max_age=60 * 60 * 24, immutable=True, public=True)
@login_exempt
def favicon(request: HttpRequest) -> HttpResponse:
    file = (settings.BASE_DIR / "static" / "favicon.png").open("rb")
    return FileResponse(file)
