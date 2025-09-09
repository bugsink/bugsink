from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework import exceptions
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
        if len(raw) != 40 or any(c not in "0123456789abcdef" for c in raw):
            raise exceptions.AuthenticationFailed("Invalid Bearer token.")

        token_obj = AuthToken.objects.filter(token=raw).first()
        if not token_obj:
            raise exceptions.AuthenticationFailed("Invalid Bearer token.")

        return (AnonymousUser(), token_obj)

    def authenticate_header(self, request):
        # tells DRF what to send in WWW-Authenticate on 401 responses, hinting the required auth scheme
        return self.keyword
