from django.shortcuts import redirect
from django.conf import settings

from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_control
from django.http import FileResponse, HttpRequest, HttpResponse

from bugsink.decorators import login_exempt


def home(request):
    if request.user.project_set.filter(projectmembership__accepted=True).distinct().count() == 1:
        # if the user has exactly one project, we redirect them to that project
        project = request.user.project_set.get()
        return redirect("issue_list_open", project_pk=project.id)

    elif request.user.project_set.all().distinct().count() > 0:
        # note: no filter on projectmembership__accepted=True here; if there is _any_ project, we show the project list
        return redirect("project_list")

    # final fallback: show the team list
    return redirect("team_list")


@login_exempt
def trigger_error(request):
    raise Exception("Exception triggered on purpose to debug error handling")


@require_GET
@cache_control(max_age=60 * 60 * 24, immutable=True, public=True)
@login_exempt
def favicon(request: HttpRequest) -> HttpResponse:
    file = (settings.BASE_DIR / "static" / "favicon.png").open("rb")
    return FileResponse(file)
