from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bugsink.app_settings import override_settings
from bsmain.models import AuthToken
from teams.models import Team
from projects.models import Project


class ProjectApiTests(TransactionTestCase):
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

    @override_settings(MAX_RETENTION_PER_PROJECT_EVENT_COUNT=1)
    def test_create_validations(self):
        r = self.client.post(
            reverse("api:project-list"),
            {"team": str(self.team.id), "name": "Core", "visibility": "team_members", "retention_max_event_count": 5},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertTrue("retention_max_event_count" in r.json())

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


class ExpansionTests(TransactionTestCase):
    """
    Expansion tests are exercised via ProjectViewSet, but the intent is to validate the
    generic ExpandableSerializerMixin infrastructure.
    """

    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.team = Team.objects.create(name="T")
        self.project = Project.objects.create(name="P", team=self.team)

    def _get(self, expand=None):
        url = reverse("api:project-detail", args=[self.project.id])
        qp = {"expand": expand} if expand else {}
        return self.client.get(url, qp)

    def test_default_no_expand(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # team is just rendered as a reference, not expanded
        self.assertEqual(data["team"], str(self.team.id))

    def test_with_valid_expand(self):
        r = self._get("team")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # team is fully expanded into object
        self.assertEqual(data["team"]["id"], str(self.team.id))
        self.assertEqual(data["team"]["name"], self.team.name)

    def test_with_invalid_expand(self):
        r = self._get("not_a_field")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            r.json(),
            {"expand": ["Unknown field: not_a_field"]},
        )

    def test_with_comma_separated_expands(self):
        # only 'team' is valid, 'not_a_field' should trigger 400
        r = self._get("team,not_a_field")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            r.json(),
            {"expand": ["Unknown field: not_a_field"]},
        )

    def test_expand_rejected_when_not_supported(self):
        # ProjectListSerializer does not support expand
        url = reverse("api:project-list")
        r = self.client.get(url, {"expand": "team"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            r.json(),
            {"expand": ["Expansions are not supported on this endpoint."]},
        )
