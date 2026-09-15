from collections import namedtuple
from functools import wraps

from django.views.decorators.http import require_http_methods
from drf_spectacular.utils import extend_schema


REQUIRED_CAPABILITY_EXTENSION = "x-bugsink-required-capability"

CAPABILITIES = {
    "issues:read": "View issues and their details.",
    "events:read": "View events, including event data and stacktraces.",
    "issues:comment": "Add comments to issues.",
    "issues:triage": "Resolve, reopen, mute, and unmute issues.",
    "issues:delete": "Delete issues.",
    "releases:read": "View releases and their details.",
    "releases:create": "Create releases.",
    "debug-files:upload": "Upload and assemble debug files and artifact bundles.",
    "projects:read": "View projects and their details.",
    "projects:manage": "Create and update projects.",
    "teams:read": "View teams and their details.",
    "teams:manage": "Create and update teams.",
}

CAPABILITY_FIELD_NAMES = {
    name: name.replace(":", "_").replace("-", "_")
    for name in CAPABILITIES
}

INSTALLATION_ONLY_CAPABILITIES = {
    "projects:read",
    "projects:manage",
    "teams:read",
    "teams:manage",
}


Lookup = namedtuple("Lookup", "using key")
TokenGuard = namedtuple("TokenGuard", "capability object_type lookup")


def lookup(*, url=None, query=None, serializer=None):
    values = {using: key for using, key in (("url", url), ("query", query), ("serializer", serializer))
              if key is not None}
    if len(values) != 1:
        raise ValueError("Specify exactly one lookup source.")
    return Lookup(*next(iter(values.items())))


def required_capability(capability_name, methods=None):
    if capability_name not in CAPABILITIES:
        raise ValueError("Unknown capability: %s" % capability_name)

    def decorator(view):
        normalized_methods = None if methods is None else tuple(method.upper() for method in methods)

        if normalized_methods is not None:
            # if methods=... is set (which it is for plain django views); actually restrict the view to those methods
            allowed_methods = normalized_methods
            if "GET" in normalized_methods and "HEAD" not in normalized_methods:
                allowed_methods += ("HEAD",)
            view = require_http_methods(allowed_methods)(view)
            view.api_http_methods = normalized_methods

        view.required_capability = capability_name
        return extend_schema(
            extensions={REQUIRED_CAPABILITY_EXTENSION: capability_name},
            methods=normalized_methods,
        )(view)

    return decorator


def get_required_capability(view):
    return getattr(view, "required_capability", None)


def token_guard(
    capability_name,
    *,
    guarding_project=None,
    guarding_issue=None,
    guarding_event=None,
    guarding_release=None,
    guarding_team=None,
):
    """Require a capability and inject its guarded project, issue, event, release, or team into the view."""
    if capability_name not in CAPABILITIES:
        raise ValueError("Unknown capability: %s" % capability_name)

    guards = {
        object_type: object_lookup
        for object_type, object_lookup in (
            ("project", guarding_project),
            ("issue", guarding_issue),
            ("event", guarding_event),
            ("release", guarding_release),
            ("team", guarding_team),
        )
        if object_lookup is not None
    }
    if len(guards) > 1:
        raise ValueError("Token operations can guard only one resource.")

    object_type, object_lookup = next(iter(guards.items()), (None, None))
    if object_type is None and capability_name not in INSTALLATION_ONLY_CAPABILITIES:
        raise ValueError("Capability %s must guard a resource." % capability_name)
    if object_lookup is not None and not isinstance(object_lookup, Lookup):
        raise TypeError("Token guard lookups must come from lookup().")

    guard = TokenGuard(capability_name, object_type, object_lookup)

    def decorator(view_method):
        @wraps(view_method)
        def guarded_view_method(view, request, *args, **kwargs):
            # Lazy import to avoid circular imports while DRF sets up permissions.
            from bugsink.api_authorization import resolve_token_guard

            kwargs.update(resolve_token_guard(view, request, guard, kwargs))
            return view_method(view, request, *args, **kwargs)

        guarded_view_method.token_guard = guard
        return required_capability(capability_name)(guarded_view_method)

    return decorator


def get_token_guard(view_method):
    return getattr(view_method, "token_guard", None)
