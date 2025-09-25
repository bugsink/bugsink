from rest_framework.permissions import BasePermission

from bsmain.models import AuthToken


class IsGlobalAuthenticated(BasePermission):
    """Allows access only to authenticated users with a valid (global) AuthToken."""

    def has_permission(self, request, view):
        return isinstance(request.auth, AuthToken)
