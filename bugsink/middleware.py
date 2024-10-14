import logging
from time import time
import os
from sentry_sdk_extensions.nohub import capture_exception

from django.contrib.auth.decorators import login_required
from django.db import connection

performance_logger = logging.getLogger("bugsink.performance.views")


class DisallowChunkedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "HTTP_TRANSFER_ENCODING" in request.META and \
                request.META["HTTP_TRANSFER_ENCODING"].lower() == "chunked" and \
                not request.META.get("wsgi.input_terminated"):

            # If we get here, it means that the request has a Transfer-Encoding header with a value of "chunked", but we
            # have no wsgi-layer handling for that. This probably means that we're running the Django development
            # server, and as such our fixes for the Gunicorn/Django mismatch that we put in wsgi.py are not in effect.
            raise ValueError("This server is not configured to support Chunked Transfer Encoding (for requests)")

        return self.get_response(request)


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        # returning None is interpreted by Django as "proceed with handling it"; we do this for all cases where we
        # have determined that the user is authenticated or user authentication is not required

        if request.user.is_authenticated:
            return None

        # we explicitly ignore the admin and accounts paths, and the api; we can always push this to a setting later
        for path in ["/admin", "/accounts", "/api"]:
            if request.path.startswith(path):
                return None

        if getattr(view_func, 'login_exempt', False):
            return None

        # Note: this short-circuits the rest of the middleware handling. That's OK in this case though, because what we
        # do amounts to "redirect and do something else". (It's not OK in the general case, where you just want to do a
        # small middleware-like thing and proceed normally otherwise)
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


class CaptureExceptionsMiddleware:
    # Capture exceptions using a Middleware rather than the more magical sentry_sdk.init() method. This is more
    # explicit and easier to understand, though less feature-complete.

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        dsn = os.getenv("SENTRY_DSN")
        if dsn is not None:
            capture_exception(dsn, exception)
        return None
