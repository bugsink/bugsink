from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from users.models import EmailVerification

from .models import Team, TeamMembership, TeamRole

User = get_user_model()


class TeamInviteLinkTestCase(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username="team-admin@example.com",
            email="team-admin@example.com",
            password="test",
        )
        self.team = Team.objects.create(name="Invite Team")
        TeamMembership.objects.create(team=self.team, user=self.admin, role=TeamRole.ADMIN, accepted=True)
        self.client.force_login(self.admin)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend")
    def test_invite_shows_link_when_email_backend_does_not_deliver(self):
        response = self.client.post(reverse("team_members_invite", kwargs={"team_pk": self.team.pk}), {
            "email": "new-team-member@example.com",
            "role": TeamRole.MEMBER,
            "action": "invite",
        })

        user = User.objects.get(username="new-team-member@example.com")
        verification = EmailVerification.objects.get(user=user)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invite link")
        self.assertContains(response, reverse("team_members_accept_new_user", kwargs={
            "team_pk": self.team.pk,
            "token": verification.token,
        }))
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=user, accepted=False).exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend")
    def test_members_page_replaces_reinvite_with_copy_invite_link(self):
        user = User.objects.create_user(
            username="pending-team-member@example.com",
            email="pending-team-member@example.com",
            is_active=False,
        )
        TeamMembership.objects.create(team=self.team, user=user, accepted=False)

        response = self.client.get(reverse("team_members", kwargs={"team_pk": self.team.pk}))

        self.assertContains(response, "Copy invite link")
        self.assertNotContains(response, "Reinvite")


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
