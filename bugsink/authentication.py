from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework import exceptions
from drf_spectacular.extensions import OpenApiAuthenticationExtension

from bsmain.models import AuthToken


def get_token_for_authentication(raw_token):
    """gets the AuthToken object for the given raw token, or None if the token is invalid or expired"""

    token = AuthToken.objects.select_related("user", "project").filter(token=raw_token).first()
    if token is None or (token.expires_at is not None and token.expires_at <= timezone.now()):
        return None

    try:
        # Reject inconsistent configurations, including is_x_boundness invalidated by an inactive user/deleted project
        token.clean()
    except ValidationError:
        return None

    return token


class BearerTokenAuthentication(BaseAuthentication):
    """
    Accepts: Authorization: Bearer <40-hex>
    Returns (AnonymousUser, AuthToken) on success; leaves request.user anonymous.
    """
    keyword = "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization")
        if not header or not header.startswith(f"{self.keyword} "):
            return None

        raw = header[len(self.keyword) + 1:].strip()

        if " " in raw:
            hint, _ = raw.split(" ", 1)
            if len(hint) <= 20:  # arbitrary cutoff to lower chance of echoing tokens in error messages
                # typically: 'Bearer Bearer abcd1234'
                raise exceptions.AuthenticationFailed("Invalid Authorization: '%s %s ...'" % (self.keyword, hint))

        if len(raw) != 40 or any(c not in "0123456789abcdef" for c in raw):
            raise exceptions.AuthenticationFailed("Malformed Bearer token, must be 40 lowercase hex chars.")

        token_obj = get_token_for_authentication(raw)
        if token_obj is None:
            raise exceptions.AuthenticationFailed("Invalid Bearer token.")

        return (AnonymousUser(), token_obj)

    def authenticate_header(self, request):
        # tells DRF what to send in WWW-Authenticate on 401 responses, hinting the required auth scheme
        return self.keyword


class BearerTokenAuthenticationExtension(OpenApiAuthenticationExtension):
    # auto-discovered b/c authentication is loaded in settnigs and this is a subclass of OpenApiAuthenticationExtension
    target_class = 'bugsink.authentication.BearerTokenAuthentication'
    name = 'BearerAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'token',
        }
