from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bsmain.models import AuthToken
from teams.models import Team
from projects.models import Project


class ProjectApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.team = Team.objects.create(name="Engineering")

    def test_list_orders_by_name_and_hides_deleted(self):
        Project.objects.create(team=self.team, name="Zebra")
        Project.objects.create(team=self.team, name="Alpha")
        Project.objects.create(team=self.team, name="Gamma", is_deleted=True)

        r = self.client.get(reverse("api:project-list"))
        self.assertEqual(r.status_code, 200)
        names = [row["name"] for row in r.json()["results"]]
        self.assertEqual(names, ["Alpha", "Zebra"])

    def test_optional_team_filter(self):
        other = Team.objects.create(name="Ops")
        Project.objects.create(team=self.team, name="A1")
        Project.objects.create(team=other, name="B1")

        r = self.client.get(reverse("api:project-list"), {"team": str(self.team.id)})
        self.assertEqual(r.status_code, 200)
        names = [row["name"] for row in r.json()["results"]]
        self.assertEqual(names, ["A1"])

    def test_create_requires_team_and_name(self):
        r1 = self.client.post(reverse("api:project-list"), {"name": "ProjOnly"}, format="json")
        self.assertEqual(r1.status_code, 400)
        self.assertIn("team", r1.json())

        r2 = self.client.post(reverse("api:project-list"), {"team": str(self.team.id)}, format="json")
        self.assertEqual(r2.status_code, 400)
        self.assertIn("name", r2.json())

    def test_create_and_retrieve(self):
        r = self.client.post(
            reverse("api:project-list"),
            {"team": str(self.team.id), "name": "Core", "visibility": "team_members"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        pid = r.json()["id"]

        r2 = self.client.get(reverse("api:project-detail", args=[pid]))
        self.assertEqual(r2.status_code, 200)
        body = r2.json()
        self.assertEqual(body["name"], "Core")
        self.assertEqual(body["visibility"], "team_members")
        self.assertIn("dsn", body)  # read-only; present on detail

    def test_patch_minimal(self):
        p = Project.objects.create(team=self.team, name="Old")
        r = self.client.patch(
            reverse("api:project-detail", args=[p.id]),
            {"name": "New", "alert_on_unmute": False},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["name"], "New")
        self.assertFalse(body["alert_on_unmute"])

    def test_delete_not_allowed(self):
        p = Project.objects.create(team=self.team, name="Temp")
        r = self.client.delete(reverse("api:project-detail", args=[p.id]))
        self.assertEqual(r.status_code, 405)
