"""
In this module we reproduce the CSRF protection steps that Django takes in the CsrfViewMiddleware, in order to provide
more detailed information about why CSRF protection might fail in a given setup. Reference: Django 4.2 / 5.1 (they are
equivalent for our purposes, proof:

git diff 5.1 4.2 -- django/middleware/csrf.py
"""

from urllib.parse import urlparse

from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import (
    CsrfViewMiddleware, RejectRequest, REASON_BAD_ORIGIN, DisallowedHost, REASON_NO_REFERER, REASON_MALFORMED_REFERER,
    REASON_INSECURE_REFERER, REASON_BAD_REFERER)
from django.utils.http import is_same_domain

from django.shortcuts import render
from django.conf import settings
from django.http import Http404

from bugsink.app_settings import get_settings
from bugsink.decorators import login_exempt


def _origin_verified_steps(middleware, request):
    # "good_host" just means "based on the Host header, after Django has sanitized it".
    # "good_origin" is the same as "good_host", but with the scheme prepended.
    # "request_origin" is the Origin header (which is present, because _origin_verified is only called if it is).
    # the expected flow for Bugsink is: good_origin == request_origin, i.e. not CORS.

    result = {}

    result["request_origin"] = request.META["HTTP_ORIGIN"]
    try:
        result["good_host"] = request.get_host()
    except DisallowedHost:
        result["good_host"] = "DisallowedHost"
        result["good_origin"] = "not available (DisallowedHost)"
    else:
        result["good_origin"] = "%s://%s" % ("https" if request.is_secure() else "http", result["good_host"],)
        if result["request_origin"] == result["good_origin"]:
            result["code_path"] = "OV1 - request_origin == good_origin"
            result["_origin_verified"] = True
            return result

    # Note: only below this line do we start to check the origin against CSRF_TRUSTED_ORIGINS.

    result["allowed_origins_exact"] = middleware.allowed_origins_exact
    if result["request_origin"] in middleware.allowed_origins_exact:
        result["code_path"] = "OV2 - exact match with allowed_origins_exact"
        result["_origin_verified"] = True
        return result
    try:
        parsed_origin = urlparse(result["request_origin"])
    except ValueError:
        result["code_path"] = "OV3 - Origin header cannot be parsed"
        result["_origin_verified"] = False
        return result

    result["request_scheme"] = parsed_origin.scheme  # more like "origin_scheme", but we're sticking to Django's names.
    result["request_netloc"] = parsed_origin.netloc  # more like "origin_netloc", but we're sticking to Django's names.
    result["allowed_origin_subdomains"] = middleware.allowed_origin_subdomains
    result["matched_subdomains"] = [
        (result["request_netloc"], host)
        for host in middleware.allowed_origin_subdomains.get(result["request_scheme"], ())
        if is_same_domain(result["request_netloc"], host)
        ]

    if any(result["matched_subdomains"]):
        result["code_path"] = "OV4 - any matched subdomain"
        result["_origin_verified"] = "OK"
    else:
        result["code_path"] = "OV5 - not any matched_subdomain"
        result["_origin_verified"] = "FAIL"

    return result


def _check_referrer_steps(middleware, request):
    result = {}
    result["referer"] = request.META.get("HTTP_REFERER")
    if result["referer"] is None:
        result["code_path"] = "CR1 - no referer"
        result["_check_referer"] = "FAILS WITH %s" % REASON_NO_REFERER
        return result

    try:
        parsed_referer = urlparse(result["referer"])
    except ValueError:
        result["code_path"] = "CR2 - parsed_referer ValueError"
        result["_check_referer"] = "FAILS WITH %s" % REASON_MALFORMED_REFERER
        return result

    if "" in (parsed_referer.scheme, parsed_referer.netloc):
        result["code_path"] = "CR3 - empty scheme or netloc"
        result["_check_referer"] = "FAILS WITH %s" % REASON_MALFORMED_REFERER
        return result

    if parsed_referer.scheme != "https":
        result["code_path"] = "CR4 - referer scheme is not https"
        result["_check_referer"] = "FAILS WITH %s" % REASON_INSECURE_REFERER
        return result

    result["csrf_trusted_origins_hosts"] = middleware.csrf_trusted_origins_hosts
    result["same_domains"] = [
        host for host in result["csrf_trusted_origins_hosts"] if is_same_domain(parsed_referer.netloc, host)]

    if result["same_domains"]:
        result["code_path"] = "CR5 - any is_same_domain(parsed_referer.netloc, host)"
        result["_check_referer"] = "OK"
        return result

    if settings.CSRF_USE_SESSIONS:
        result["good_referer"] = settings.SESSION_COOKIE_DOMAIN
        result["good_referrer_code_path"] = "SESSION_COOKIE_DOMAIN"
    else:
        result["good_referer"] = settings.CSRF_COOKIE_DOMAIN
        result["good_referrer_code_path"] = "CSRF_COOKIE_DOMAIN"

    if result["good_referer"] is None:
        try:
            result["good_referer"] = request.get_host()
            result["good_referrer_code_path"] = "request.get_host()"
        except DisallowedHost:
            result["code_path"] = "CR6 - good_referrer through request.get_host(): DisallowedHost"
            result["_check_referer"] = "FAILS WITH %s" % REASON_BAD_REFERER % parsed_referer.geturl()
            return result

    else:
        server_port = request.get_port()
        if server_port not in ("443", "80"):
            result["good_referer"] = "%s:%s" % (result["good_referer"], server_port)

    if not is_same_domain(parsed_referer.netloc, result["good_referer"]):
        result["code_path"] = "CR7 - not is_same_domain(parsed_referer.netloc, good_referer)"
        result["_check_referer"] = "FAILS WITH %s" % REASON_BAD_REFERER % parsed_referer.geturl()
        return result

    result["code_path"] = "CR8 - is_same_domain(parsed_referer.netloc, good_referer)"
    result["_check_referer"] = "OK"
    return result


def _process_view_steps(middleware, request, wider_context):
    result = {}

    result["request_is_secure"] = request.is_secure()

    # we don't reproduce the first 4 steps because they represent various ways of saying "no CSRF protection needed".
    # 1. if getattr(request, "csrf_processing_done", False):
    # 2. if getattr(callback, "csrf_exempt", False):
    # 3. if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
    # 4. if getattr(request, "_dont_enforce_csrf_checks", False):

    if "HTTP_ORIGIN" in request.META:
        result["code_path"] = "PV1 - _origin_verified"
        wider_context["origin_verified_steps"] = _origin_verified_steps(middleware, request)

        result["_orgin_verified"] = "OK" if middleware._origin_verified(request) else \
            "FAILS WITH %s" % REASON_BAD_ORIGIN % request.META["HTTP_ORIGIN"]

        if result["_orgin_verified"] != "OK":
            result["process_view"] = "FAILS at _check_origin"
            return result

    elif request.is_secure():
        result["code_path"] = "PV2 - _check_referer"
        wider_context["check_referer_steps"] = _check_referrer_steps(middleware, request)

        try:
            middleware._check_referer(request)
            result["check_referer"] = "OK"
        except RejectRequest as e:
            result["check_referer"] = "FAILS WITH %s" % e.reason
            result["process_view"] = "FAILS at _check_referer"
            return result

    else:
        result["code_path"] = "PV3 - (just) _check_token"

    try:
        middleware._check_token(request)
        result["_check_token"] = "OK"
    except RejectRequest as e:
        result["_check_token"] = "FAILS WITH %s" % e.reason
        result["process_view"] = "FAILS at _check_token"
        return result

    result["process_view"] = "OK"
    return result


@csrf_exempt  # obviously needs to be off, because the whole reason you're here is because you're not able to pass it.
@login_exempt  # when you're debugging CSRF, logging in is probably impossible.
def csrf_debug(request):
    # provide as complete information as possible about "where CSRF fails" (if it does), at least as it can be seen from
    # the vantage point of Bugsink/Django.

    # note the absence of cookie-related information; AFAIK, we don't use cookies for CSRF protection in Bugsink, so
    # there's no need to check for them.

    if not (settings.DEBUG_CSRF is True or (settings.DEBUG_CSRF == "USE_DEBUG" and settings.DEBUG)):
        # We do this here, and not in urls.py, because urls.py cannot be changed on-demand in tests
        raise Http404("This view is only available in DEBUG_CSRF mode.")

    context = {"relevant_settings": {"BASE_URL": str(get_settings().BASE_URL)}}
    context["relevant_settings"].update({k: getattr(settings, k) for k in [
        "ALLOWED_HOSTS",
        "SECURE_PROXY_SSL_HEADER",
        "CSRF_TRUSTED_ORIGINS",
    ]})

    if request.method == "POST":
        middleware = CsrfViewMiddleware(get_response="dummy value")

        context.update({
            "posted": True,
            "POST": request.POST,
            "META": {
                k: request.META.get(k) for k in [
                    "HTTP_ORIGIN",
                    "HTTP_REFERER",
                ]
            },
            "process_view": _process_view_steps(middleware, request, context),
        })

        # Note: for _check_token we don't provide a detailed breakdown; we believe wrong setups are unlikely to
        # cause it to fail, and wrong (e.g. proxy) setups is what we're trying to diagnose here.
        return render(request, "bugsink/csrf_debug.html", context)

    return render(request, "bugsink/csrf_debug.html", context)
