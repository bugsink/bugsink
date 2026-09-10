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


def required_capability(capability_name, methods=None):
    if capability_name not in CAPABILITIES:
        raise ValueError("Unknown capability: %s" % capability_name)

    def decorator(view):
        view.required_capability = capability_name
        if methods is not None:
            # TODO: enforce this declaration at runtime when the Sentry-compatible bearer capability checks are added.
            view.api_http_methods = tuple(method.upper() for method in methods)

        return extend_schema(
            extensions={REQUIRED_CAPABILITY_EXTENSION: capability_name},
            methods=methods,
        )(view)

    return decorator


def get_required_capability(view):
    return getattr(view, "required_capability", None)


def get_view_required_capability(view):
    return get_required_capability(getattr(view, view.action))
