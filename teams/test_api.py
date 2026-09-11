from django.contrib.auth import get_user_model
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bugsink.app_settings import CB_NOBODY, override_settings
from bsmain.models import AuthToken
from teams.models import Team, TeamMembership, TeamRole, TeamVisibility


class TeamApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(teams_read=True, teams_manage=True)
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

    def test_malformed_id_is_404(self):
        r = self.client.get(reverse("api:team-detail", args=["not-a-uuid"]))
        self.assertEqual(r.status_code, 404)

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

    def test_personal_token_lists_only_teams_visible_to_its_user(self):
        user = get_user_model().objects.create_user(username="team-reader")
        member_team = Team.objects.create(name="Member team", visibility=TeamVisibility.HIDDEN)
        TeamMembership.objects.create(team=member_team, user=user, accepted=True)
        visible_team = Team.objects.create(name="Visible team", visibility=TeamVisibility.DISCOVERABLE)
        hidden_team = Team.objects.create(name="Hidden team", visibility=TeamVisibility.HIDDEN)
        token = AuthToken.objects.create(is_user_bound=True, user=user, teams_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.get(reverse("api:team-list"))
        hidden_detail = self.client.get(reverse("api:team-detail", args=[hidden_team.id]))

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {str(member_team.id), str(visible_team.id)},
            {row["id"] for row in response.json()["results"]},
        )
        self.assertEqual(403, hidden_detail.status_code)

    def test_personal_token_can_create_a_team_when_members_can_create_teams(self):
        user = get_user_model().objects.create_user(username="team-creator")
        token = AuthToken.objects.create(is_user_bound=True, user=user, teams_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.post(reverse("api:team-list"), {"name": "Created team"}, format="json")

        self.assertEqual(201, response.status_code)

    def test_personal_token_cannot_create_a_team_when_team_creation_is_disabled(self):
        user = get_user_model().objects.create_user(username="blocked-team-creator")
        token = AuthToken.objects.create(is_user_bound=True, user=user, teams_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        with override_settings(TEAM_CREATION=CB_NOBODY):
            response = self.client.post(reverse("api:team-list"), {"name": "Forbidden team"}, format="json")

        self.assertEqual(403, response.status_code)
        self.assertFalse(Team.objects.filter(name="Forbidden team").exists())

    def test_personal_team_admin_can_update_the_team(self):
        team = Team.objects.create(name="Administered team")
        user = get_user_model().objects.create_user(username="team-admin")
        TeamMembership.objects.create(team=team, user=user, role=TeamRole.ADMIN, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, teams_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.patch(
            reverse("api:team-detail", args=[team.id]),
            {"name": "Updated team"},
            format="json",
        )

        self.assertEqual(200, response.status_code)

    def test_personal_team_member_cannot_update_the_team(self):
        team = Team.objects.create(name="Member team")
        user = get_user_model().objects.create_user(username="team-member")
        TeamMembership.objects.create(team=team, user=user, role=TeamRole.MEMBER, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, teams_manage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.patch(
            reverse("api:team-detail", args=[team.id]),
            {"name": "Forbidden update"},
            format="json",
        )

        self.assertEqual(403, response.status_code)
        team.refresh_from_db()
        self.assertEqual("Member team", team.name)
