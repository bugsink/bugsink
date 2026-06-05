from django.contrib.auth import get_user_model

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from .models import Team, TeamMembership, TeamRole

User = get_user_model()


class TeamScopedActionTestCase(TransactionTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="team-admin", password="test")
        self.team = Team.objects.create(name="owned")
        TeamMembership.objects.create(team=self.team, user=self.user, role=TeamRole.ADMIN, accepted=True)
        self.client.force_login(self.user)

    def test_member_remove_scopes_to_team(self):
        other_user = User.objects.create_user(username="other", password="test")
        other_team = Team.objects.create(name="other")
        other_membership = TeamMembership.objects.create(team=other_team, user=other_user)

        response = self.client.post(
            f"/teams/{self.team.id}/members/",
            {"action": f"remove:{other_user.id}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TeamMembership.objects.filter(id=other_membership.id).exists())
