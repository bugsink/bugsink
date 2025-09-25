from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bsmain.models import AuthToken
from teams.models import Team


class TeamApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

    def test_list_ordering_by_name(self):
        Team.objects.create(name="Zeta")
        Team.objects.create(name="Alpha")
        Team.objects.create(name="Gamma")
        r = self.client.get(reverse("api:team-list"))
        self.assertEqual(r.status_code, 200)
        names = [row["name"] for row in r.json()["results"]]
        self.assertEqual(names, ["Alpha", "Gamma", "Zeta"])

    def test_create_requires_name(self):
        r = self.client.post(reverse("api:team-list"), {"visibility": "discoverable"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"name": ["This field is required."]})

    def test_create_minimal_and_retrieve(self):
        r = self.client.post(
            reverse("api:team-list"),
            {"name": "Core Team", "visibility": "discoverable"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        team_id = r.json()["id"]

        r2 = self.client.get(reverse("api:team-detail", args=[team_id]))
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["name"], "Core Team")
        self.assertEqual(r2.json()["visibility"], "discoverable")

    def test_patch_minimal(self):
        team = Team.objects.create(name="Old Name")
        r = self.client.patch(
            reverse("api:team-detail", args=[team.id]),
            {"name": "New Name"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "New Name")

    def test_delete_not_allowed(self):
        team = Team.objects.create(name="Temp")
        r = self.client.delete(reverse("api:team-detail", args=[team.id]))
        self.assertEqual(r.status_code, 405)

    def test_create_rejects_invalid_visibility(self):
        r = self.client.post(
            reverse("api:team-list"),
            {"name": "Bad", "visibility": "nope"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"visibility": ['"nope" is not a valid choice.']})
