import logging
from urllib.parse import urlencode, urlparse

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, SuspiciousOperation
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext as _
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.views import OIDCAuthenticationCallbackView, OIDCAuthenticationRequestView

from bugsink.app_settings import get_settings


logger = logging.getLogger("bugsink.oidc")


DISCOVERABLE_SETTINGS = {
    "OIDC_OP_AUTHORIZATION_ENDPOINT": "authorization_endpoint",
    "OIDC_OP_TOKEN_ENDPOINT": "token_endpoint",
    "OIDC_OP_USER_ENDPOINT": "userinfo_endpoint",
    "OIDC_OP_JWKS_ENDPOINT": "jwks_uri",
    "OIDC_OP_LOGOUT_ENDPOINT": "end_session_endpoint",
    "OIDC_OP_ISSUER": "issuer",
}

_discovery_document = None


def get_discovery_document():
    global _discovery_document
    if _discovery_document is None:
        response = requests.get(settings.OIDC_OP_DISCOVERY_URL, timeout=settings.OIDC_TIMEOUT)
        response.raise_for_status()
        _discovery_document = response.json()
    return _discovery_document


def oidc_setting(attr, *default):
    """Like mozilla_django_oidc's import_from_settings, but with a fallback to the provider's discovery document."""
    value = getattr(settings, attr, None)
    if value is None and attr in DISCOVERABLE_SETTINGS and settings.OIDC_OP_DISCOVERY_URL:
        value = get_discovery_document().get(DISCOVERABLE_SETTINGS[attr])

    if value is not None:
        return value
    if default:
        return default[0]
    raise ImproperlyConfigured(f"Setting {attr} not found (and not discoverable)")


def absolute_url(path):
    # path (from reverse() inside a request) already includes the script prefix, i.e. BASE_URL's path; take the origin
    base_url = urlparse(get_settings().BASE_URL)
    return f"{base_url.scheme}://{base_url.netloc}{path}"


def callback_url():
    return absolute_url(reverse("oidc_authentication_callback"))


def get_groups(claims):
    groups = claims.get(settings.OIDC_GROUPS_CLAIM) or []
    return [groups] if isinstance(groups, str) else groups


def claims_rejection_reason(claims):
    if not claims.get("email"):
        return "no 'email' claim; is the 'email' scope requested and released? Received claims: %s" % sorted(claims)

    if settings.OIDC_REQUIRE_VERIFIED_EMAIL and claims.get("email_verified") not in (True, "true"):
        return "'email_verified' is %r; verify the email at the IdP or set OIDC_REQUIRE_VERIFIED_EMAIL=false" % (
            claims.get("email_verified"),)

    if settings.OIDC_REQUIRED_GROUP is not None and settings.OIDC_REQUIRED_GROUP not in get_groups(claims):
        return "not in OIDC_REQUIRED_GROUP %r; claim %r is %r" % (
            settings.OIDC_REQUIRED_GROUP, settings.OIDC_GROUPS_CLAIM, claims.get(settings.OIDC_GROUPS_CLAIM))

    return None


def _lazy_setting(attr, *default):
    return property(lambda self: oidc_setting(attr, *default))


class OIDCBackend(OIDCAuthenticationBackend):
    get_settings = staticmethod(oidc_setting)

    # Resolved lazily rather than in __init__: Django instantiates every backend on each password login too, and that
    # must neither fail when OIDC is disabled nor hit the network (break-glass login while the IdP is down).
    OIDC_OP_TOKEN_ENDPOINT = _lazy_setting("OIDC_OP_TOKEN_ENDPOINT")
    OIDC_OP_USER_ENDPOINT = _lazy_setting("OIDC_OP_USER_ENDPOINT")
    OIDC_OP_JWKS_ENDPOINT = _lazy_setting("OIDC_OP_JWKS_ENDPOINT", None)
    OIDC_RP_CLIENT_ID = _lazy_setting("OIDC_RP_CLIENT_ID")
    OIDC_RP_CLIENT_SECRET = _lazy_setting("OIDC_RP_CLIENT_SECRET")
    OIDC_RP_SIGN_ALGO = _lazy_setting("OIDC_RP_SIGN_ALGO", "RS256")
    OIDC_RP_IDP_SIGN_KEY = _lazy_setting("OIDC_RP_IDP_SIGN_KEY", None)

    def __init__(self, *args, **kwargs):
        self.UserModel = get_user_model()

    def authenticate(self, request, **kwargs):
        if not settings.OIDC_ENABLED:
            return None

        try:
            return super().authenticate(request, **kwargs)
        except SuspiciousOperation as e:
            # e.g. a token with a bad signature or audience; the library would turn this into a bare 400
            logger.warning("OIDC login rejected: %s", e)
            return None

    def get_token(self, payload):
        payload["redirect_uri"] = callback_url()
        return super().get_token(payload)

    def _verify_jws(self, payload, key):
        # the library checks signature, algorithm and expiry, but not audience and issuer
        claims = super()._verify_jws(payload, key)

        audience = claims.get("aud")
        if self.OIDC_RP_CLIENT_ID not in (audience if isinstance(audience, list) else [audience]):
            raise SuspiciousOperation("OIDC token audience does not match OIDC_RP_CLIENT_ID")

        issuer = self.get_settings("OIDC_OP_ISSUER", None)
        if issuer is not None and claims.get("iss") != issuer:
            raise SuspiciousOperation("OIDC token issuer does not match the provider's issuer")

        return claims

    def get_userinfo(self, access_token, id_token, payload):
        # some providers (e.g. Entra ID) put the groups in the ID token only
        return {**payload, **super().get_userinfo(access_token, id_token, payload)}

    def verify_claims(self, claims):
        reason = claims_rejection_reason(claims)
        if reason is not None:
            logger.warning("OIDC login rejected for %s: %s", claims.get("email", "<no email>"), reason)
        return reason is None

    def filter_users_by_claims(self, claims):
        return self.UserModel.objects.filter(username__iexact=claims["email"])

    def create_user(self, claims):
        if get_settings().SINGLE_USER:
            return None

        email = claims["email"]
        user = self.UserModel.objects.create_user(
            username=email,
            email=email,
            first_name=claims.get("given_name", ""),
            last_name=claims.get("family_name", ""),
        )
        return self.update_user(user, claims)

    def update_user(self, user, claims):
        if not user.is_active and user.last_login is None and not user.has_usable_password():
            # a pending invite: the IdP has verified the email address, which is what the invite link would have done
            user.is_active = True

        if settings.OIDC_ADMIN_GROUP is not None:
            user.is_superuser = user.is_staff = settings.OIDC_ADMIN_GROUP in get_groups(claims)

        user.save()
        return user


class AuthenticationRequestView(OIDCAuthenticationRequestView):
    get_settings = staticmethod(oidc_setting)

    def get_extra_params(self, request):
        return {**super().get_extra_params(request), "redirect_uri": callback_url()}


class AuthenticationCallbackView(OIDCAuthenticationCallbackView):
    def login_failure(self):
        messages.error(self.request, _("Single sign-on failed. Please try again or contact your administrator."))
        return HttpResponseRedirect(reverse("login") + "?local=1")


def oidc_authenticate(request):
    if not settings.OIDC_ENABLED:
        raise Http404("OIDC is not enabled")
    return AuthenticationRequestView.as_view()(request)


def oidc_callback(request):
    if not settings.OIDC_ENABLED:
        raise Http404("OIDC is not enabled")
    return AuthenticationCallbackView.as_view()(request)


def oidc_logout_url(request):
    """The provider's end-session URL for an OIDC-logged-in session, or None (to just log out locally)."""
    id_token = request.session.get("oidc_id_token")
    if not settings.OIDC_ENABLED or id_token is None:
        return None

    try:
        end_session_endpoint = oidc_setting("OIDC_OP_LOGOUT_ENDPOINT", None)
    except requests.RequestException:
        return None  # logging out locally must always work, even when the IdP is unreachable

    if end_session_endpoint is None:
        return None

    return end_session_endpoint + "?" + urlencode({
        "id_token_hint": id_token,
        "client_id": settings.OIDC_RP_CLIENT_ID,
        "post_logout_redirect_uri": absolute_url(reverse("login") + "?local=1"),
    })
