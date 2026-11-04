from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from bsmain.models import AuthToken
from bugsink.app_settings import get_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from mcpserver.models import McpToolCall, OAuthGrant


def make_grant(user):
    auth_token = AuthToken.objects.create(
        is_user_bound=True, user=user, issues_read=True, expires_at=timezone.now() + timedelta(hours=1))
    return OAuthGrant.objects.create(
        auth_token=auth_token, client_id="x", client_name="Claude Code",
        refresh_expires_at=timezone.now() + timedelta(days=30))


class ConnectionsTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.alice = get_user_model().objects.create_user(username="alice")
        self.bob = get_user_model().objects.create_user(username="bob")
        self.client.force_login(self.alice)

    def test_lists_own_grants_and_setup(self):
        own, other = make_grant(self.alice), make_grant(self.bob)
        response = self.client.get("/oauth/connections/")
        self.assertContains(response, f'value="{own.pk}"')
        self.assertNotContains(response, f'value="{other.pk}"')
        self.assertContains(response, f"bugsink {get_settings().BASE_URL}/mcp")

    def test_disconnect_deletes_token(self):
        grant = make_grant(self.alice)
        response = self.client.post("/oauth/connections/", {"disconnect": grant.pk})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuthToken.objects.exists())

    def test_cannot_disconnect_other_users_grant(self):
        grant = make_grant(self.bob)
        response = self.client.post("/oauth/connections/", {"disconnect": grant.pk})
        self.assertEqual(response.status_code, 404)
        self.assertTrue(OAuthGrant.objects.filter(pk=grant.pk).exists())

    def test_token_list_hides_oauth_tokens(self):
        grant = make_grant(self.alice)
        response = self.client.get("/bsmain/auth_tokens/")
        self.assertNotContains(response, grant.auth_token.token)
        self.assertContains(response, "/oauth/connections/")

    def test_shows_own_tool_calls(self):
        McpToolCall.objects.create(user=self.alice, client_name="Claude Code", tool="get_issue", arguments={})
        McpToolCall.objects.create(user=self.bob, client_name="Cursor", tool="resolve_issue", arguments={})
        response = self.client.get("/oauth/connections/")
        self.assertContains(response, "get_issue")
        self.assertNotContains(response, "resolve_issue")
