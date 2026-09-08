from drf_spectacular.utils import extend_schema


REQUIRED_CAPABILITIES_EXTENSION = "x-bugsink-required-capabilities"

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


def required_capabilities(*capability_names, methods=None):
    if not capability_names:
        raise ValueError("At least one capability is required.")

    unknown_capabilities = set(capability_names) - set(CAPABILITIES)
    if unknown_capabilities:
        raise ValueError("Unknown capabilities: %s" % ", ".join(sorted(unknown_capabilities)))

    def decorator(view):
        view.required_capabilities = tuple(capability_names)
        if methods is not None:
            # TODO: enforce this declaration at runtime when the Sentry-compatible bearer capability checks are added.
            view.api_http_methods = tuple(method.upper() for method in methods)

        return extend_schema(
            extensions={REQUIRED_CAPABILITIES_EXTENSION: list(capability_names)},
            methods=methods,
        )(view)

    return decorator


def get_required_capabilities(view):
    return getattr(view, "required_capabilities", ())
