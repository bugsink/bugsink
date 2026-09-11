from django.contrib.auth import get_user_model
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bugsink.app_settings import override_settings
from bsmain.models import AuthToken
from teams.models import Team, TeamMembership, TeamRole
from projects.models import Project, ProjectMembership, ProjectRole, ProjectVisibility


class ProjectApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(projects_read=True, projects_manage=True)
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

    def test_create_scopes_name_uniqueness_to_team(self):
        Project.objects.create(team=self.team, name="Backend")

        r = self.client.post(
            reverse("api:project-list"),
            {"team": str(self.team.id), "name": "Backend"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("non_field_errors", r.json())

        other_team = Team.objects.create(name="Operations")
        r = self.client.post(
            reverse("api:project-list"),
            {"team": str(other_team.id), "name": "Backend"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)

    def test_malformed_id_is_404(self):
        r = self.client.get(reverse("api:project-detail", args=["not-an-int"]))
        self.assertEqual(r.status_code, 404)

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

    def test_patch_rejects_duplicate_name_in_team(self):
        Project.objects.create(team=self.team, name="Backend")
        project = Project.objects.create(team=self.team, name="Frontend")

        r = self.client.patch(
            reverse("api:project-detail", args=[project.id]),
            {"name": "Backend"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("non_field_errors", r.json())

    def test_patch_does_not_move_project_to_another_team(self):
        project = Project.objects.create(team=self.team, name="Backend")
        other_team = Team.objects.create(name="Operations")

        r = self.client.patch(
            reverse("api:project-detail", args=[project.id]),
            {"team": str(other_team.id)},
            format="json",
        )

        self.assertEqual(r.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.team, self.team)

    def test_delete_not_allowed(self):
        p = Project.objects.create(team=self.team, name="Temp")
        r = self.client.delete(reverse("api:project-detail", args=[p.id]))
        self.assertEqual(r.status_code, 405)

    def test_patch_list_not_allowed(self):
        r = self.client.patch(reverse("api:project-list"), {"name": "No object"}, format="json")
        self.assertEqual(r.status_code, 405)

    def test_personal_token_lists_only_projects_visible_to_its_user(self):
        user = get_user_model().objects.create_user(username="project-reader")
        member_project = Project.objects.create(
            team=self.team,
            name="Member project",
            visibility=ProjectVisibility.TEAM_MEMBERS,
        )
        ProjectMembership.objects.create(project=member_project, user=user, accepted=True)

        team = Team.objects.create(name="Readers team")
        TeamMembership.objects.create(team=team, user=user, accepted=True)
        team_project = Project.objects.create(
            team=team,
            name="Team project",
            visibility=ProjectVisibility.TEAM_MEMBERS,
        )

        visible_project = Project.objects.create(name="Visible project", visibility=ProjectVisibility.DISCOVERABLE)
        hidden_project = Project.objects.create(name="Hidden project", visibility=ProjectVisibility.TEAM_MEMBERS)
        token = AuthToken.objects.create(is_user_bound=True, user=user, projects_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.get(reverse("api:project-list"))
        hidden_detail = self.client.get(reverse("api:project-detail", args=[hidden_project.id]))

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {member_project.id, team_project.id, visible_project.id},
            {row["id"] for row in response.json()["results"]},
        )
        self.assertEqual(403, hidden_detail.status_code)
        self.assertEqual(
            "This project is not visible to the user bound to this token.",
            hidden_detail.json()["detail"],
        )

    def test_personal_team_admin_can_create_and_update_projects(self):
        user = get_user_model().objects.create_user(username="project-team-admin")
        TeamMembership.objects.create(team=self.team, user=user, role=TeamRole.ADMIN, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, projects_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        create_response = self.client.post(
            reverse("api:project-list"),
            {"team": self.team.id, "name": "Created by team admin"},
            format="json",
        )
        project = Project.objects.get(name="Created by team admin")
        update_response = self.client.patch(
            reverse("api:project-detail", args=[project.id]),
            {"name": "Updated by team admin"},
            format="json",
        )

        self.assertEqual(201, create_response.status_code)
        self.assertEqual(200, update_response.status_code)

    def test_personal_project_admin_can_update_a_project(self):
        project = Project.objects.create(team=self.team, name="Project-admin project")
        user = get_user_model().objects.create_user(username="project-admin")
        ProjectMembership.objects.create(
            project=project,
            user=user,
            role=ProjectRole.ADMIN,
            accepted=True,
        )
        token = AuthToken.objects.create(is_user_bound=True, user=user, projects_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.patch(
            reverse("api:project-detail", args=[project.id]),
            {"name": "Project-admin update"},
            format="json",
        )

        self.assertEqual(200, response.status_code)

    def test_personal_project_member_cannot_create_or_update_projects(self):
        project = Project.objects.create(team=self.team, name="Member project")
        user = get_user_model().objects.create_user(username="project-member")
        ProjectMembership.objects.create(project=project, user=user, role=ProjectRole.MEMBER, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, projects_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        create_response = self.client.post(
            reverse("api:project-list"),
            {"team": self.team.id, "name": "Forbidden project"},
            format="json",
        )
        update_response = self.client.patch(
            reverse("api:project-detail", args=[project.id]),
            {"name": "Forbidden update"},
            format="json",
        )

        self.assertEqual(403, create_response.status_code)
        self.assertEqual(
            "The user bound to this token does not administer this team.",
            create_response.json()["detail"],
        )
        self.assertEqual(403, update_response.status_code)
        self.assertEqual(
            "The user bound to this token does not administer this project.",
            update_response.json()["detail"],
        )
        project.refresh_from_db()
        self.assertEqual("Member project", project.name)


class ExpansionTests(TransactionTestCase):
    """
    Expansion tests are exercised via ProjectViewSet, but the intent is to validate the
    generic ExpandableSerializerMixin infrastructure.
    """

    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(projects_read=True)
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
