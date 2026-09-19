from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied

from bugsink.api_capabilities import get_required_capability
from bugsink.utils import assert_
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

        action = view.action

        # We arrive here for OPTIONS requests because for those, DRF sets view.action to "metadata", then clones the
        # request (with method set to POST/PUT), all such that it can figure out which methods to advertise. In that
        # case we need to look up the actual action ourselves.
        if action == "metadata":
            action = view.action_map.get(request.method.lower())

        # DRF sets action to None for methods not mapped on this route; we pass-through so DRF can return 405.
        if action is None:
            return True

        required_capability = get_required_capability(getattr(view, action))

        # Canonical API operations have this (test_all_registered_api_operations_have_an_authentication_classification);
        # It is security-sensitive code, so assert it here too.
        assert_(required_capability is not None, "API operation must declare a required capability.")

        if required_capability not in request.auth.capabilities:
            raise PermissionDenied("This token does not have the required capability: %s." % required_capability)

        return True
