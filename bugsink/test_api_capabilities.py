import unittest
from collections import Counter

from django.urls import URLResolver, get_resolver
from drf_spectacular.generators import SchemaGenerator

from bugsink.api_capabilities import CAPABILITIES, get_required_capabilities


# the reviewed contract between capabilities and the operations they protect. (in our codebase, these facts are spread
# across the `@capability_required` decorators on each view which makes it hard to see the whole picture at once).
EXPECTED_CAPABILITY_OPERATIONS = {
    "canonical": {
        "issues:read": {
            "GET /api/canonical/0/issues/",
            "GET /api/canonical/0/issues/{id}/",
        },
        "events:read": {
            "GET /api/canonical/0/events/",
            "GET /api/canonical/0/events/{id}/",
            "GET /api/canonical/0/events/{id}/stacktrace/",
        },
        "issues:comment": {
            "POST /api/canonical/0/issue-comments/",
        },
        "issues:triage": {
            "POST /api/canonical/0/issues/{id}/mute/",
            "POST /api/canonical/0/issues/{id}/mute-for/",
            "POST /api/canonical/0/issues/{id}/mute-until/",
            "POST /api/canonical/0/issues/{id}/reopen/",
            "POST /api/canonical/0/issues/{id}/resolve/",
            "POST /api/canonical/0/issues/{id}/resolve-latest/",
            "POST /api/canonical/0/issues/{id}/resolve-next/",
            "POST /api/canonical/0/issues/{id}/unmute/",
        },
        "issues:delete": {
            "DELETE /api/canonical/0/issues/{id}/",
        },
        "releases:read": {
            "GET /api/canonical/0/releases/",
            "GET /api/canonical/0/releases/{id}/",
        },
        "releases:create": {
            "POST /api/canonical/0/releases/",
        },
        "projects:read": {
            "GET /api/canonical/0/projects/",
            "GET /api/canonical/0/projects/{id}/",
        },
        "projects:manage": {
            "POST /api/canonical/0/projects/",
            "PATCH /api/canonical/0/projects/{id}/",
        },
        "teams:read": {
            "GET /api/canonical/0/teams/",
            "GET /api/canonical/0/teams/{id}/",
        },
        "teams:manage": {
            "POST /api/canonical/0/teams/",
            "PATCH /api/canonical/0/teams/{id}/",
        },
    },
    "sentry-compatible": {
        "debug-files:upload": {
            "GET /api/0/",
            "GET /api/0/organizations/{organization_slug}/chunk-upload/",
            "POST /api/0/organizations/{organization_slug}/chunk-upload/",
            "POST /api/0/organizations/{organization_slug}/artifactbundle/assemble/",
            "POST /api/0/projects/{organization_slug}/{project_slug}/files/difs/assemble/",
        },
    },
}

# Ingestion authenticates with a project DSN, not a bearer token. Listing these operations separately protects that
# boundary: future token work must neither apply bearer capabilities to SDK ingestion nor mistake ingestion for an
# unprotected endpoint.
DSN_AUTHENTICATED_OPERATIONS = {
    ("ingest-store", "POST"),
    ("ingest-envelope", "POST"),
    ("ingest-minidump", "POST"),
    ("ingest-security", "POST"),
}

# These endpoints support or describe the API rather than expose application resources. They are intentionally outside
# bearer-capability enforcement, so every exception to capability authentication is small, named, and reviewable.
INFRASTRUCTURE_OPERATIONS = {
    ("api-root", "GET"),
    ("schema", "GET"),
    ("swagger-ui", "GET"),
    ("api_catch_all", "GET"),
    ("api_catch_all", "POST"),
    ("api_catch_all", "PUT"),
    ("api_catch_all", "PATCH"),
    ("api_catch_all", "DELETE"),
    ("api_catch_all", "TRACE"),
}


class CapabilityContractTests(unittest.TestCase):
    def setUp(self):
        # Generate the schema through the same hooks used by the served schema and Swagger UI.
        self.schema = SchemaGenerator().get_schema(request=None, public=True)

    def test_capability_operation_catalog(self):
        # Prove that the generated capability-to-operation catalog (schema) is exactly the reviewed contract above.
        capability_operations = {
            "canonical": {},
            "sentry-compatible": {},
        }

        for capability, details in self.schema["x-bugsink-capabilities"].items():
            for operation in details["operations"]:
                api = "canonical" if operation["path"].startswith("/api/canonical/") else "sentry-compatible"
                capability_operations[api].setdefault(capability, set()).add(
                    "%s %s" % (operation["method"], operation["path"])
                )

        self.assertEqual(EXPECTED_CAPABILITY_OPERATIONS, capability_operations)

        # ensure  every declared capability protects at least one operation, avoiding dead code.
        self.assertEqual(set(CAPABILITIES), {
            capability
            for api in EXPECTED_CAPABILITY_OPERATIONS.values()
            for capability in api
        })

    def test_all_registered_api_operations_have_an_authentication_classification(self):
        # Loop over the actual URL resolver and require every API HTTP operation to be bearer-capability, DSN,
        # or infrastructure. This guards against accidentally exposing a new endpoint without an explicit authentication
        # class. If a new endpoint is added to the API, it must be classified in this test, and if it is not, the test
        # will fail.
        actual_bearer_capabilities = Counter()
        actual_dsn_operations = set()
        actual_infrastructure_operations = set()
        unclassified_operations = set()

        # walk the URL resolver tree to find every registered API route.
        patterns_to_visit = [("", get_resolver().url_patterns)]
        registered_api_patterns = []
        while patterns_to_visit:
            prefix, patterns = patterns_to_visit.pop()
            for pattern in patterns:
                route = prefix + str(pattern.pattern)
                if isinstance(pattern, URLResolver):
                    patterns_to_visit.append((route, pattern.url_patterns))
                elif (
                    route.startswith("api/")
                    and "(?P<format>" not in route
                    and "<drf_format_suffix:format>" not in route
                ):
                    registered_api_patterns.append(pattern)

        # Expand every registered route into its actual HTTP operations and read capability annotations from the
        # callable that enforcement will use.
        registered_api_operations = []
        all_methods = ("GET", "POST", "PUT", "PATCH", "DELETE", "TRACE")
        for pattern in registered_api_patterns:
            callback = pattern.callback

            if getattr(callback, "actions", None):
                # i.e. a DRF ViewSet.
                for method, action in callback.actions.items():
                    if method not in callback.cls.http_method_names or method in ("head", "options"):
                        continue
                    registered_api_operations.append(
                        (pattern.name, method.upper(), get_required_capabilities(getattr(callback.cls, action)))
                    )
                continue

            if getattr(callback, "view_class", None) is not None:
                # i.e. Django/DRF class-based view
                for method in callback.view_class.http_method_names:
                    if method in ("head", "options") or not hasattr(callback.view_class, method):
                        continue
                    registered_api_operations.append(
                        (pattern.name, method.upper(), get_required_capabilities(callback.view_class))
                    )
                continue

            # implied by continues in the above: from now on callback is a plain Django function-based view.
            # TODO: when capability checks are enforced, also enforce this declared method list at runtime and test
            # that the declaration and runtime behavior match.
            methods = getattr(callback, "api_http_methods", None)
            if methods is None and pattern.name == "api_catch_all":
                methods = all_methods

            if methods is None:
                registered_api_operations.append((pattern.name, None, get_required_capabilities(callback)))
                continue

            for method in methods:
                registered_api_operations.append((pattern.name, method, get_required_capabilities(callback)))

        # Collect the actual operations into the three authentication classes and compare to the reviewed contract
        # above.
        for name, method, capabilities in registered_api_operations:
            operation = (name, method)
            if operation in DSN_AUTHENTICATED_OPERATIONS:
                self.assertFalse(capabilities)
                actual_dsn_operations.add(operation)
            elif operation in INFRASTRUCTURE_OPERATIONS:
                self.assertFalse(capabilities)
                actual_infrastructure_operations.add(operation)
            elif capabilities:
                actual_bearer_capabilities.update(capabilities)
            else:
                unclassified_operations.add(operation)

        expected_bearer_capabilities = Counter({
            capability: len(operations)
            for api in EXPECTED_CAPABILITY_OPERATIONS.values()
            for capability, operations in api.items()
        })
        self.assertEqual(set(), unclassified_operations)
        self.assertEqual(expected_bearer_capabilities, actual_bearer_capabilities)
        self.assertEqual(DSN_AUTHENTICATED_OPERATIONS, actual_dsn_operations)
        self.assertEqual(INFRASTRUCTURE_OPERATIONS, actual_infrastructure_operations)

    def test_required_capabilities_are_in_operation_documentation(self):
        # Prove that every bearer endpoint tells human readers which capability it requires (in the OpenAPI schema)
        for details in self.schema["x-bugsink-capabilities"].values():
            for catalog_operation in details["operations"]:
                operation = self.schema["paths"][catalog_operation["path"]][catalog_operation["method"].lower()]
                capabilities = operation["x-bugsink-required-capabilities"]
                for capability in capabilities:
                    self.assertIn("`%s`" % capability, operation["description"])
