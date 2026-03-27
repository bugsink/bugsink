import logging
from time import time

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.utils.translation import get_supported_language_variant
from django.utils.translation.trans_real import parse_accept_lang_header
from django.utils import translation
from django.urls import get_script_prefix
from django.http import HttpResponseBadRequest, Http404

from bugsink.app_settings import get_settings


performance_logger = logging.getLogger("bugsink.performance.views")


class ContentEncodingCheckMiddleware:
    """
    We don't just globally interpret Content-Encoding for all views since:

    1. this increases our attack service (or forces us to reason about how it doesn't)
    2. forces us to think about the interplay of Django's POST/FILES handling and maximums (DATA_UPLOAD_MAX_MEMORY_SIZE)
       and our own maximums and handling.
    3. the various maximums for reading from streaming requests are per-view (underlying data-type) anyway.

    Instead, the only global thing we do is "fail explicitly".
    """

    # NOTE: once this list becomes long, we could switch to a per-view decorator (with the maximum bytes as a value)
    SUPPORTED_VIEWS = [
        "ingest-store",
        "ingest-envelope",
        "ingest-minidump",

        "api_catch_all",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.resolver_match:
            view_name = request.resolver_match.view_name
        else:
            view_name = "[unknown]"

        if "HTTP_CONTENT_ENCODING" in request.META and view_name not in self.SUPPORTED_VIEWS:
            return HttpResponseBadRequest(f"Content-Encoding handling is not supported for endpoint `{view_name}`")

        return None  # proceed normally


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
    # NOTE: this predates Django 5.1's built-in LoginRequiredMiddleware; we may want to switch to that at some point,
    # but for now we have something that works and there's no real upside so we'll leave it as is.

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
            if request.path.startswith(get_script_prefix().rstrip("/") + path):
                return None

        if getattr(view_func, 'login_exempt', False):
            return None

        # Note: this short-circuits the rest of the middleware handling. That's OK in this case though, because what we
        # do amounts to "redirect and do something else". (It's not OK in the general case, where you just want to do a
        # small middleware-like thing and proceed normally otherwise)
        return login_required(view_func)(request, *view_args, **view_kwargs)


class AdminRequiresSettingMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/") and not get_settings().USE_ADMIN:
            raise Http404

        return self.get_response(request)


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


class SetRemoteAddrMiddleware:
    """
    Sets the REMOTE_ADDR from the proxy headers if so configured. Sets REMOTE_ADDR to None if the configured headers are
    empty (misconfiguration), i.e. None rather than 127.0.0.1 in that case.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def parse_x_forwarded_for(header_value):
        # NOTE: our method parsing _does not_ remove port numbers from the X-Forwarded-For header; such setups are rare
        # (but legal according to the spec) but [1] we don't recommend them and [2] we recommend X-Real-IP over
        # X-Forwarded-For anyway.
        # https://serverfault.com/questions/753682/iis-server-farm-with-arr-why-does-http-x-forwarded-for-have-a-port-nu

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
            # NOTE: X-Real-IP never contains a port number AFAICT by searching online so the below is IP-only:
            request.META["REMOTE_ADDR"] = request.META.get("HTTP_X_REAL_IP", None)

        elif settings.USE_X_FORWARDED_FOR:  # elif: X-Real-IP / X-Forwarded-For are mutually exclusive
            request.META["REMOTE_ADDR"] = self.parse_x_forwarded_for(request.META.get("HTTP_X_FORWARDED_FOR", None))

        return self.get_response(request)


def language_from_accept_language(request):
    """
    Pick a language using ONLY the Accept-Language header. Ignores URL prefixes, session, and cookies.  I prefer to have
    as little "magic" in the language selection as possible, and I _know_ we don't do anything with paths, so I'd rather
    not have such code invoked at all (at the cost of reimplementing some of Django's logic here).
    """
    header = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    for lang_code, _q in parse_accept_lang_header(header):
        try:
            # strict=False lets country variants match (e.g. 'es-CO' for 'es')
            return get_supported_language_variant(lang_code, strict=False)
        except LookupError:
            continue
    return settings.LANGUAGE_CODE


def get_chosen_language(request_user, request):
    if request_user.is_authenticated and request_user.language != "auto":
        return get_supported_language_variant(request_user.language, strict=False)
    return language_from_accept_language(request)


class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        translation.activate(get_chosen_language(request.user, request))
        response = self.get_response(request)
        return response
