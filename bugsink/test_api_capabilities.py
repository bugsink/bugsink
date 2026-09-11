import unittest
from collections import Counter

from django.http import JsonResponse
from django.test import RequestFactory, TransactionTestCase
from django.urls import URLResolver, get_resolver
from drf_spectacular.generators import SchemaGenerator

from bugsink.api_capabilities import CAPABILITIES, get_required_capability, get_token_guard
from bsmain.models import AuthToken
from files.views import requires_auth_token


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
                    registered_api_patterns.append((route, pattern))

        # Expand every registered route into its actual HTTP operations and read capability annotations from the
        # callable that enforcement will use.
        registered_api_operations = []
        all_methods = ("GET", "POST", "PUT", "PATCH", "DELETE", "TRACE")
        request_factory = RequestFactory()

        for route, pattern in registered_api_patterns:
            callback = pattern.callback

            if getattr(callback, "actions", None):
                # i.e. a DRF ViewSet.
                for method, action in callback.actions.items():
                    if method not in callback.cls.http_method_names or method in ("head", "options"):
                        continue
                    view_method = getattr(callback.cls, action)
                    if route.startswith("api/canonical/"):
                        # For canonical DRF endpoints, we require that the view method has a token guard, i.e. that it's
                        # _actually_ enforcing the capability check at runtime, not just documenting it. (for other
                        # endpoints this is still TODO)
                        self.assertIsNotNone(get_token_guard(view_method))
                    registered_api_operations.append(
                        (pattern.name, method.upper(), get_required_capability(view_method))
                    )
                continue

            if getattr(callback, "view_class", None) is not None:
                # i.e. Django/DRF class-based view
                for method in callback.view_class.http_method_names:
                    if method in ("head", "options") or not hasattr(callback.view_class, method):
                        continue  # skip unimplemented / uninteresting methods

                    capability = get_required_capability(getattr(callback.view_class, method))

                    # Here we assert that capability is not so-set; the inverse (that each API view has a capability or
                    # is from a list of known exceptions) is in the below "reviewed contract" tests
                    self.assertIsNone(
                        capability,
                        "Capability enforcement is not implemented for Django/DRF class-based views, "
                        "so capabilities are disallowed there",
                    )

                    registered_api_operations.append(
                        (pattern.name, method.upper(), capability)
                    )

                continue

            # final special case: the catch-all which isn't really that interesting.
            if pattern.name == "api_catch_all":
                registered_api_operations.extend((pattern.name, method, None) for method in all_methods)
                continue

            # implied by continues in the above: from now on callback is a plain Django function-based view.
            capability = get_required_capability(callback)
            methods = getattr(callback, "api_http_methods", None)
            self.assertIsNotNone(capability, "plain Django view %s must declare a required capability" % callback)
            self.assertIsNotNone(methods, "plain Django view %s must declare its HTTP methods" % callback)

            # As built, we made it a hard requirement that plain Django API views (which currently map to the
            # Sentry-compatible API) use @requires_auth_token. It is fine to change that assumption in the
            # future, but the assertion below ensures that this is done explicitly.
            self.assertIs(requires_auth_token, getattr(callback, "_required_capability_enforcer", None))

            # For plain Django views, we require that the methods attribute is actually enforced (for DRF this is done
            # by the framework). We do this by calling the view with every HTTP method and checking the response code.
            # Declared methods reach authentication (401); undeclared methods stop at Django's method check (405).
            for method in all_methods:
                response = callback(request_factory.generic(method, "/"))
                self.assertEqual(401 if method in methods else 405, response.status_code)

            for method in methods:
                registered_api_operations.append((pattern.name, method, capability))

        # Collect the actual operations into the three authentication classes and compare to the reviewed contract
        # above.
        for name, method, capability in registered_api_operations:
            operation = (name, method)
            if operation in DSN_AUTHENTICATED_OPERATIONS:
                self.assertIsNone(capability)
                actual_dsn_operations.add(operation)
            elif operation in INFRASTRUCTURE_OPERATIONS:
                self.assertIsNone(capability)
                actual_infrastructure_operations.add(operation)
            elif capability is not None:
                actual_bearer_capabilities[capability] += 1
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

    def test_required_capability_is_in_operation_documentation(self):
        # Prove that every bearer endpoint tells human readers which capability it requires (in the OpenAPI schema)
        for details in self.schema["x-bugsink-capabilities"].values():
            for catalog_operation in details["operations"]:
                operation = self.schema["paths"][catalog_operation["path"]][catalog_operation["method"].lower()]
                capability = operation["x-bugsink-required-capability"]
                self.assertIn("`%s`" % capability, operation["description"])


class RequiresAuthTokenTests(TransactionTestCase):
    def test_token_without_required_capability_is_rejected(self):
        # This decorator requires debug-files:upload; the token has only issues:read.
        token = AuthToken.objects.create(issues_read=True)

        @requires_auth_token("debug-files:upload", methods=["GET"])
        def view(request):
            return JsonResponse({"reached": True})

        response = view(RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token.token}"))

        self.assertEqual(403, response.status_code)
        self.assertJSONEqual(
            response.content,
            {"error": "This token does not have the required capability: debug-files:upload."},
        )
