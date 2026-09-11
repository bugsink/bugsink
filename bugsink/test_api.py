import unittest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from drf_spectacular.generators import SchemaGenerator

from bugsink.api_capabilities import CAPABILITY_FIELD_NAMES, INSTALLATION_ONLY_CAPABILITIES
from bsmain.models import AuthToken
from issues.factories import get_or_create_issue
from projects.models import Project, ProjectMembership


class BearerAuthRouterTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name="Valid token project")
        self.issue, _ = get_or_create_issue(self.project)

    def test_valid_token_binding_combinations_authenticate(self):
        user = get_user_model().objects.create_user(username="valid-token-user")
        ProjectMembership.objects.create(project=self.project, user=user, accepted=True)
        tokens = [
            AuthToken.objects.create(events_read=True),
            AuthToken.objects.create(is_project_bound=True, project=self.project, events_read=True),
            AuthToken.objects.create(is_user_bound=True, user=user, events_read=True),
            AuthToken.objects.create(
                is_user_bound=True,
                user=user,
                is_project_bound=True,
                project=self.project,
                events_read=True,
            ),
        ]

        for token in tokens:
            with self.subTest(is_user_bound=token.is_user_bound, is_project_bound=token.is_project_bound):
                self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
                response = self.client.get(reverse("api:event-list"), {"issue": self.issue.id})
                self.assertEqual(200, response.status_code)

    def test_missing_on_event_list(self):
        resp = self.client.get(reverse("api:event-list"))
        self.assertIn(resp.status_code, (401, 403))

    def test_invalid_on_event_list(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + "a" * 40)
        resp = self.client.get(reverse("api:event-list"))
        self.assertEqual(resp.status_code, 401)

    def test_missing_required_capability_is_rejected(self):
        # Event list requires events:read; this token has only issues:read.
        token = AuthToken.objects.create(issues_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.get(reverse("api:event-list"))

        self.assertEqual(403, response.status_code)
        self.assertEqual("This token does not have the required capability: events:read.", response.json()["detail"])

    def test_revoked_token_is_rejected(self):
        token = AuthToken.objects.create(events_read=True)
        token.revoke()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        resp = self.client.get(reverse("api:event-list"))

        self.assertEqual(resp.status_code, 401)

    def test_token_with_future_expiration_authenticates(self):
        token = AuthToken.objects.create(
            expires_at=timezone.now() + timedelta(days=30),
            events_read=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.get(reverse("api:event-list"), {"issue": self.issue.id})

        self.assertEqual(200, response.status_code)

    def test_personal_token_with_inactive_user_is_rejected(self):
        user = get_user_model().objects.create_user(username="inactive", is_active=False)
        token = AuthToken.objects.create(is_user_bound=True, user=user, events_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        resp = self.client.get(reverse("api:event-list"))

        self.assertEqual(resp.status_code, 401)

    def test_tokens_with_invalid_current_configuration_are_rejected(self):
        user = get_user_model().objects.create_user(username="token-user")
        project = Project.objects.create(name="Token project")
        deleted_project = Project.objects.create(name="Deleted token project", is_deleted=True)

        # Save invalid rows directly to prove authentication does not rely on creation-time validation having run.
        invalid_tokens = [
            ("user on a service token", AuthToken.objects.create(user=user)),
            ("missing bound user", AuthToken.objects.create(is_user_bound=True)),
            ("project on an installation token", AuthToken.objects.create(project=project)),
            ("missing bound project", AuthToken.objects.create(is_project_bound=True)),
            (
                "deleted bound project",
                AuthToken.objects.create(is_project_bound=True, project=deleted_project),
            ),
        ]
        invalid_tokens.extend(
            (
                capability,
                AuthToken.objects.create(
                    is_project_bound=True,
                    project=project,
                    **{CAPABILITY_FIELD_NAMES[capability]: True},
                ),
            )
            for capability in INSTALLATION_ONLY_CAPABILITIES
        )

        for invalid_reason, token in invalid_tokens:
            with self.subTest(invalid_reason=invalid_reason):
                self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
                response = self.client.get(reverse("api:event-list"))
                self.assertEqual(401, response.status_code)


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
