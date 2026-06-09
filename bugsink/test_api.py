import unittest
from django.urls import reverse
from rest_framework.test import APIClient
from drf_spectacular.generators import SchemaGenerator

from bsmain.models import AuthToken


class BearerAuthRouterTests(unittest.TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_ok_on_event_list(self):
        token = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        resp = self.client.get(reverse("api:event-list"), {"issue": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(resp.status_code, 200)

    def test_missing_on_event_list(self):
        resp = self.client.get(reverse("api:event-list"))
        self.assertIn(resp.status_code, (401, 403))

    def test_invalid_on_event_list(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + "a" * 40)
        resp = self.client.get(reverse("api:event-list"))
        self.assertEqual(resp.status_code, 401)


class OpenAPISchemaTests(unittest.TestCase):
    # LLM-generated; not deeply inspected. We'll leave these in to have _some_ coverage of these bits in the tests.

    def setUp(self):
        self.schema = SchemaGenerator().get_schema(request=None, public=True)

    def test_includes_sentry_compatible_api_paths(self):
        paths = self.schema["paths"]
        expected_paths = {
            "/api/0/",
            "/api/0/organizations/{organization_slug}/chunk-upload/",
            "/api/0/organizations/{organization_slug}/artifactbundle/assemble/",
            "/api/0/projects/{organization_slug}/{project_slug}/files/difs/assemble/",
            "/api/{project_pk}/store/",
            "/api/{project_pk}/envelope/",
            "/api/{project_pk}/minidump/",
            "/api/{project_pk}/security/",
        }

        self.assertTrue(expected_paths <= set(paths))
        self.assertEqual({"get"}, set(paths["/api/0/"]))
        self.assertEqual({"get", "post"}, set(paths["/api/0/organizations/{organization_slug}/chunk-upload/"]))
        self.assertEqual({"post"}, set(paths["/api/{project_pk}/envelope/"]))

    def test_describes_sentry_compatible_api_boundary(self):
        tags = {tag["name"]: tag for tag in self.schema["tags"]}

        self.assertIn("Sentry-compatible API", tags)
        self.assertEqual(
            "`/api/0` and `/api/{project_pk}/` paths exist for Sentry-SDK / sentry-cli compatibility "
            "(as opposed to the `/api/canonical/` paths which are Bugsink-specific).",
            tags["Sentry-compatible API"]["description"],
        )

    def test_manual_api_paths_are_at_the_bottom(self):
        paths = list(self.schema["paths"])

        self.assertEqual(
            [
                "/api/0/",
                "/api/0/organizations/{organization_slug}/chunk-upload/",
                "/api/0/organizations/{organization_slug}/artifactbundle/assemble/",
                "/api/0/projects/{organization_slug}/{project_slug}/files/difs/assemble/",
                "/api/{project_pk}/store/",
                "/api/{project_pk}/envelope/",
                "/api/{project_pk}/minidump/",
                "/api/{project_pk}/security/",
            ],
            paths[-8:],
        )

    def test_manual_api_tags_are_at_the_bottom(self):
        tags = [tag["name"] for tag in self.schema["tags"]]

        self.assertEqual(["Sentry-compatible API", "CSP reporting"], tags[-2:])

    def test_documents_csp_reporting_separately(self):
        tags = {tag["name"]: tag for tag in self.schema["tags"]}
        operation = self.schema["paths"]["/api/{project_pk}/security/"]["post"]

        self.assertIn("CSP reporting", tags)
        self.assertEqual(["CSP reporting"], operation["tags"])
        self.assertIn("browser-emitted CSP violation reports", operation["description"])
        self.assertEqual([{"SentryKeyQuery": []}], operation["security"])

    def test_keeps_canonical_api_paths_and_security_schemes(self):
        paths = self.schema["paths"]
        security_schemes = self.schema["components"]["securitySchemes"]

        self.assertIn("/api/canonical/0/events/", paths)
        self.assertIn("BearerAuth", security_schemes)
        self.assertIn("SentryAuthHeader", security_schemes)
        self.assertIn("SentryKeyQuery", security_schemes)

    def test_does_not_document_api_catch_all(self):
        self.assertNotIn("/api/{subpath}", self.schema["paths"])
