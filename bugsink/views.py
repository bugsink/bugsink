import sys

from django.http import HttpResponseServerError, HttpResponseBadRequest
from django.template import TemplateDoesNotExist, loader
from django.views.decorators.csrf import requires_csrf_token
from django.views.defaults import ERROR_500_TEMPLATE_NAME, ERROR_PAGE_TEMPLATE, ERROR_400_TEMPLATE_NAME
from django.shortcuts import redirect
from django.conf import settings

from django.template.defaultfilters import filesizeformat
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_control
from django.http import FileResponse, HttpRequest, HttpResponse
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render

from snappea.settings import get_settings as get_snappea_settings

from bugsink.version import __version__
from bugsink.decorators import login_exempt
from bugsink.app_settings import get_settings as get_bugsink_settings

from phonehome.tasks import send_if_due


def _phone_home():
    # I need a way to cron-like run tasks that works for the setup with and without snappea. With snappea it's straight-
    # forward (though not part of snappea _yet_). Without snappea, you'd need _some_ location to do a "poor man's cron"
    # check. Server-start would be the first thing to consider, but how to do this across gunicorn, debugserver, and
    # possibly even non-standard (for Bugsink) wsgi servers? Better go the "just pick some request to do the check"
    # route. I've picked "home", because [a] it's assumed to be somewhat regularly visited [b] there's no transaction
    # logic in it, which leaves space for transaction-logic in the phone-home task itself and [c] some alternatives are
    # a no-go (ingestion: on a tight budget; login: not visited when a long-lived session is active).
    #
    # having chosen the solution for the non-snappea case, I got the crazy idea of using it for the snappea case too,
    # i.e. just put a .delay() here and let the config choose. Not so crazy though, because [a] saves us from new
    # features in snappea, [b] we introduce a certain symmetry of measurement between the 2 setups, i.e. the choice of
    # lazyness does not influence counting and [c] do I really want to get pings for sites where nobody visits home()?

    send_if_due.delay()  # _phone_home() wrapper serves as a place for the comment above


def home(request):
    _phone_home()

    if request.user.project_set.filter(projectmembership__accepted=True).distinct().count() == 1:
        # if the user has exactly one project, we redirect them to that project
        project = request.user.project_set.get()
        return redirect("issue_list_open", project_pk=project.id)

    if request.user.project_set.all().distinct().count() > 0:
        # note: no filter on projectmembership__accepted=True here; if there is _any_ project, we show the project list
        return redirect("project_list")

    if get_bugsink_settings().SINGLE_TEAM:
        # in single-team mode, there's is no (meaningful) team list. We redirect to the (empty) project list instead
        return redirect("project_list")

    # final fallback: show the team list.
    # (the assumption is: if there are no projects, the team-list is the most useful page to show, because if there are
    # no teams, this is where you can create one, and if there are teams, this is where you can select one)
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


@user_passes_test(lambda u: u.is_superuser)
def settings_view(request):
    def get_setting(settings, key):
        value = getattr(settings, key, None)
        if key in ["EMAIL_HOST_PASSWORD", "EMAIL_HOST_USER"]:
            return "********" if value else ""
        return value

    def round_values(settings):
        def maybe_round(v):
            if isinstance(v, int) and v > 0 and v % 1024 == 0:
                return "%s (%s)" % (v, filesizeformat(v))
            return v
        return {k: maybe_round(v) for k, v in settings.items()}

    misc_settings = {
        k: get_setting(settings, k) for k in (
            "ALLOWED_HOSTS",
            "SECURE_PROXY_SSL_HEADER",
            "USE_X_REAL_IP",
            "USE_X_FORWARDED_FOR",
            "X_FORWARDED_FOR_PROXY_COUNT",
            "TIME_ZONE",
            "EMAIL_HOST",
            "EMAIL_HOST_USER",
            "EMAIL_HOST_PASSWORD",
            "EMAIL_PORT",
            "EMAIL_USE_TLS",
            "EMAIL_BACKEND",
            "DEFAULT_FROM_EMAIL",
        )
    }

    return render(request, "bugsink/settings.html", {
        "bugsink_settings": round_values(get_bugsink_settings()),
        "snappea_settings": get_snappea_settings(),
        "misc_settings": misc_settings,
        "version": __version__,
    })


@requires_csrf_token
def bad_request(request, exception, template_name=ERROR_400_TEMPLATE_NAME):
    # verbatim copy of Django's default bad_request view, but with "exception" in the context
    # doing this for any-old-Django-site is probably a bad idea, but here the security/convenience tradeoff is fine,
    # especially because we only show str(exception) in the template.
    try:
        template = loader.get_template(template_name)
    except TemplateDoesNotExist:
        if template_name != ERROR_400_TEMPLATE_NAME:
            # Reraise if it's a missing custom template.
            raise
        return HttpResponseBadRequest(
            ERROR_PAGE_TEMPLATE % {"title": "Bad Request (400)", "details": ""},
        )

    _, exception, _ = sys.exc_info()
    return HttpResponseBadRequest(template.render({"exception": exception}, request))


@requires_csrf_token
def server_error(request, template_name=ERROR_500_TEMPLATE_NAME):
    # verbatim copy of Django's default server_error view, but with "exception" in the context
    # doing this for any-old-Django-site is probably a bad idea, but here the security/convenience tradeoff is fine,
    # especially because we only show str(exception) in the template.
    try:
        template = loader.get_template(template_name)
    except TemplateDoesNotExist:
        if template_name != ERROR_500_TEMPLATE_NAME:
            # Reraise if it's a missing custom template.
            raise
        return HttpResponseServerError(
            ERROR_PAGE_TEMPLATE % {"title": "Server Error (500)", "details": ""},
        )

    _, exception, _ = sys.exc_info()
    return HttpResponseServerError(template.render({"exception": exception}, request))
