import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bsmain.models import AuthToken
from teams.models import Team
from projects.models import Project, ProjectMembership, ProjectRole

from .models import MessagingServiceConfig


WEBHOOK_URL = "https://discord.com/api/webhooks/123/secret-token"


@patch("alerts.service_backends.webhook_security._resolve_ip_addresses", return_value={"162.159.135.232"})
class MessagingServiceApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(projects_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.team = Team.objects.create(name="Engineering")
        self.project = Project.objects.create(team=self.team, name="Alpha")

    def _create(self, **overrides):
        data = {"project": self.project.id, "display_name": "#alerts", "kind": "discord",
                "config": {"webhook_url": WEBHOOK_URL}}
        data.update(overrides)
        return self.client.post(reverse("api:messaging-service-list"), data, format="json")

    def test_create_discord_service(self, mock_resolve):
        response = self._create()

        self.assertEqual(201, response.status_code)
        self.assertEqual({"id", "project", "display_name", "kind"}, set(response.json()))
        self.assertNotIn("secret-token", response.content.decode())

        service = MessagingServiceConfig.objects.get()
        self.assertEqual(self.project, service.project)
        self.assertEqual("discord", service.kind)
        self.assertEqual({"webhook_url": WEBHOOK_URL}, json.loads(service.config))

    def test_create_rejects_invalid_webhook(self, mock_resolve):
        mock_resolve.return_value = {"10.0.0.1"}

        response = self._create()

        self.assertEqual(400, response.status_code)
        self.assertIn("webhook_url", response.json()["config"])
        self.assertFalse(MessagingServiceConfig.objects.exists())

    def test_create_requires_kind_and_config(self, mock_resolve):
        response = self.client.post(
            reverse("api:messaging-service-list"), {"project": self.project.id, "display_name": "x"},
            format="json")

        self.assertEqual(400, response.status_code)
        self.assertEqual({"kind", "config"}, set(response.json()))

    def test_list_is_scoped_to_project_and_hides_config(self, mock_resolve):
        other = Project.objects.create(team=self.team, name="Other")
        MessagingServiceConfig.objects.create(
            project=self.project, display_name="mine", kind="discord", config=json.dumps({"webhook_url": WEBHOOK_URL}))
        MessagingServiceConfig.objects.create(
            project=other, display_name="theirs", kind="discord", config=json.dumps({"webhook_url": WEBHOOK_URL}))

        response = self.client.get(reverse("api:messaging-service-list"), {"project": self.project.id})

        self.assertEqual(200, response.status_code)
        self.assertEqual(["mine"], [row["display_name"] for row in response.json()["results"]])
        self.assertNotIn("secret-token", response.content.decode())

    def test_list_requires_project(self, mock_resolve):
        response = self.client.get(reverse("api:messaging-service-list"))

        self.assertEqual(400, response.status_code)
        self.assertIn("project", response.json())

    def test_token_without_capability_is_refused(self, mock_resolve):
        token = AuthToken.objects.create(projects_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        list_response = self.client.get(reverse("api:messaging-service-list"), {"project": self.project.id})
        create_response = self._create()

        self.assertEqual(403, list_response.status_code)
        self.assertEqual(403, create_response.status_code)
        self.assertFalse(MessagingServiceConfig.objects.exists())

    def test_personal_project_member_is_refused(self, mock_resolve):
        user = get_user_model().objects.create_user(username="project-member")
        ProjectMembership.objects.create(project=self.project, user=user, role=ProjectRole.MEMBER, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, projects_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        list_response = self.client.get(reverse("api:messaging-service-list"), {"project": self.project.id})
        create_response = self._create(config={"webhook_url": "https://internal.example/hook"})

        self.assertEqual(403, list_response.status_code)
        self.assertEqual(403, create_response.status_code)
        self.assertEqual(
            "The user bound to this token does not administer this project.", create_response.json()["detail"])
        mock_resolve.assert_not_called()  # the webhook is not looked up for an unauthorized caller
        self.assertFalse(MessagingServiceConfig.objects.exists())

    def test_create_rejects_non_string_config_values(self, mock_resolve):
        response = self._create(kind="telegram", config={"bot_token": ["1"], "chat_id": "5"})

        self.assertEqual(400, response.status_code)
        self.assertIn("bot_token", response.json()["config"])

    def test_retrieve_is_not_supported(self, mock_resolve):
        response = self.client.get("/api/canonical/0/messaging-services/1/")

        self.assertEqual(405, response.status_code)

    def test_update_replaces_config_without_returning_secrets(self, mock_resolve):
        service_id = self._create().json()["id"]
        user = get_user_model().objects.create_user(username="project-admin")
        ProjectMembership.objects.create(project=self.project, user=user, role=ProjectRole.ADMIN, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, projects_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        new_url = "https://discord.com/api/webhooks/456/replacement-token"

        response = self.client.patch(
            reverse("api:messaging-service-detail", args=[service_id]),
            {"display_name": "New alerts", "config": {"webhook_url": new_url}}, format="json")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"id", "project", "display_name", "kind"}, set(response.json()))
        service = MessagingServiceConfig.objects.get(id=service_id)
        self.assertEqual("New alerts", service.display_name)
        self.assertEqual({"webhook_url": new_url}, json.loads(service.config))

        other = Project.objects.create(team=self.team, name="Other")
        response = self.client.patch(
            reverse("api:messaging-service-detail", args=[service_id]),
            {"display_name": "Name only", "project": other.id, "kind": "telegram"}, format="json")

        self.assertEqual(200, response.status_code)
        service.refresh_from_db()
        self.assertEqual("Name only", service.display_name)
        self.assertEqual({"webhook_url": new_url}, json.loads(service.config))
        self.assertEqual(self.project, service.project)
        self.assertEqual("discord", service.kind)

    def test_update_rejects_invalid_config(self, mock_resolve):
        service_id = self._create().json()["id"]
        mock_resolve.return_value = {"10.0.0.1"}

        response = self.client.patch(
            reverse("api:messaging-service-detail", args=[service_id]),
            {"display_name": "Changed", "config": {"webhook_url": "https://internal.example/hook"}}, format="json")

        self.assertEqual(400, response.status_code)
        service = MessagingServiceConfig.objects.get(id=service_id)
        self.assertEqual("#alerts", service.display_name)
        self.assertEqual({"webhook_url": WEBHOOK_URL}, json.loads(service.config))

    def test_personal_token_cannot_update_another_projects_destination(self, mock_resolve):
        service_id = self._create().json()["id"]
        other = Project.objects.create(team=self.team, name="Other")
        user = get_user_model().objects.create_user(username="other-admin")
        ProjectMembership.objects.create(project=other, user=user, role=ProjectRole.ADMIN, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, projects_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        mock_resolve.reset_mock()

        response = self.client.patch(
            reverse("api:messaging-service-detail", args=[service_id]),
            {"config": {"webhook_url": "https://internal.example/hook"}}, format="json")

        self.assertEqual(403, response.status_code)
        mock_resolve.assert_not_called()
        self.assertEqual({"webhook_url": WEBHOOK_URL}, json.loads(MessagingServiceConfig.objects.get().config))
