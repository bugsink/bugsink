import logging
from time import time

from django.contrib.auth.decorators import login_required
from django.db import connection

performance_logger = logging.getLogger("bugsink.performance.views")


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.user.is_authenticated:
            return

        # we explicitly ignore the admin and accounts paths, and the api; we can always push this to a setting later
        for path in ["/admin", "/accounts", "/api"]:
            if request.path.startswith(path):
                return None  # returning None is interpreted by Django as "proceed with handling it"

        if getattr(view_func, 'login_exempt', False):
            return None

        return login_required(view_func)(request, *view_args, **view_kwargs)


class PerformanceStatsMiddleware:
    """TSTTCPW to get some handle on view-performance (mostly for UI views). The direct cause for introducing this is
    that I got sent on a wild goose chase by the Django Debug Toolbar, which reported long (>100ms) CPU times for some
    view when it was the DJDT itself that was causing most of that time.

    Yes this only measures the time spent in the view function itself and not the time in the surrounding Middleware,
    but the whole point is to measure where individual views might be slow.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        t0 = time()
        result = view_func(request, *view_args, **view_kwargs)
        took = (time() - t0) * 1000
        if not request.path.startswith("/static"):
            performance_logger.info(f"{took:6.2f}ms / {len(connection.queries)} queries: '{ view_func.__name__ }'")

        return result
