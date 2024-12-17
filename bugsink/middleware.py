import logging
from time import time
import os
from sentry_sdk_extensions.nohub import capture_exception

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.conf import settings
from django.core.exceptions import SuspiciousOperation

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
            # server, and as such our fixes for the Gunicorn/Django mismatch that we put in wsgi.py are insufficient
            # (they fix Django's request handling for the Django-Gunicorn combination, but they don't make Django
            # capable of handling chunked requests on its own).
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
    # Debugging tool (for development); not turned on by default.

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        dsn = os.getenv("SENTRY_DSN")
        if dsn is not None:
            capture_exception(dsn, exception)
        return None


class SetRemoteAddrMiddleware:
    """
    Sets the REMOTE_ADDR from the proxy headers if so configured. Sets REMOTE_ADDR to None if the configured headers are
    empty (misconfiguration), i.e. None rather than 127.0.0.1 in that case.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def parse_x_forwarded_for(header_value):
        if header_value in [None, ""]:
            # The most typical misconfiguration is to forget to set the header at all, or to have it be empty. In that
            # case, we'll just set the IP to None, which will mean some data will be missing from your events (but
            # you'll still get them).
            return None

        # Elements are comma-separated, with optional whitespace surrounding the commas. (MDN)
        ips = [s.strip() for s in header_value.split(",")]

        # Each proxy in the chain appends the IP it is forwarding for to the list. Hence, the number of proxies you use
        # must exactly equal the number of IPs in the list. (+1 for the client; -1 because the last proxy will not be in
        # the list)
        if len(ips) == settings.X_FORWARDED_FOR_PROXY_COUNT:
            return ips[0]  # The first address is the original client; others are proxies

        if len(ips) > settings.X_FORWARDED_FOR_PROXY_COUNT:
            # Greater than: somebody added something, most likely maliciously. Complain loudly.
            # Alternatively, we could just take the one we trust (at index -proxy_count), but if someone's spoofing
            # there's no reason to trust the rest of the message (event data).
            raise SuspiciousOperation("X-Forwarded-For header does not contain the expected number of addresses")

        # implied: len(ips) < settings.X_FORWARDED_FOR_PROXY_COUNT:
        # As in 'if header_value is None' above, this is a misconfiguration. We'll just set the IP to None.
        return None

    def __call__(self, request):
        if settings.USE_X_REAL_IP:
            request.META["REMOTE_ADDR"] = request.META.get("HTTP_X_REAL_IP", None)

        elif settings.USE_X_FORWARDED_FOR:  # elif: X-Real-IP / X-Forwarded-For are mutually exclusive
            request.META["REMOTE_ADDR"] = self.parse_x_forwarded_for(request.META.get("HTTP_X_FORWARDED_FOR", None))

        return self.get_response(request)
