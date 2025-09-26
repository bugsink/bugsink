from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework import exceptions
from drf_spectacular.extensions import OpenApiAuthenticationExtension

from bsmain.models import AuthToken


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

        token_obj = AuthToken.objects.filter(token=raw).first()
        if not token_obj:
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
