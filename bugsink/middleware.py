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
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.view_name = "<<unknown>>"

    def __call__(self, request):
        t0 = time()
        result = self.get_response(request)
        took = (time() - t0) * 1000
        performance_logger.info(f"{took:6.2f}ms / {len(connection.queries)} queries: '{ self.view_name }'")
        return result

    def process_view(self, request, view_func, view_args, view_kwargs):
        self.view_name = view_func.__name__
        return None
