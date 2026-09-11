from rest_framework.permissions import BasePermission

from bugsink.api_capabilities import get_view_required_capability
from bsmain.models import AuthToken


class IsAuthTokenAuthenticated(BasePermission):
    """Allows access only to requests authenticated with an AuthToken."""

    def has_permission(self, request, view):
        return isinstance(request.auth, AuthToken)


class HasRequiredCapability(BasePermission):
    def has_permission(self, request, view):
        # OPTIONS only describes the endpoint, so it does not require an operation capability.
        if request.method == "OPTIONS":
            return True

        # Methods disabled on the ViewSet are not API operations; we pass-through so DRF can return 405.
        if request.method.lower() not in view.http_method_names:
            return True

        # DRF sets action to None for methods not mapped on this route; we pass-through so DRF can return 405.
        if view.action is None:
            return True

        required_capability = get_view_required_capability(view)
        return required_capability is not None and required_capability in request.auth.capabilities
