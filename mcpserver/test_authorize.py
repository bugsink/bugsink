from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth import get_user_model
from django.test import Client

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from mcpserver.models import OAuthAuthorizationCode
from mcpserver.oauth import sign_client
from projects.models import Project, ProjectMembership

CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
CALLBACK = "http://localhost:5555/callback"


class AuthorizeTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="alice")
        self.client.force_login(self.user)
        self.params = {
            "response_type": "code",
            "client_id": sign_client("Claude Code", ["http://localhost:1234/callback"]),
            "redirect_uri": CALLBACK,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "state": "xyz",
        }

    def url(self, **overrides):
        return "/oauth/authorize?" + urlencode({**self.params, **overrides})

    def query_of(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(CALLBACK + "?"))
        return {key: values[0] for key, values in parse_qs(urlsplit(response["Location"]).query).items()}

    def test_anonymous_is_sent_to_login(self):
        response = Client().get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response["Location"])
        self.assertIn("oauth/authorize", response["Location"])

    def test_shows_consent_with_defaults(self):
        response = self.client.get(self.url())
        self.assertContains(response, "Claude Code")
        form = response.context["form"]
        self.assertTrue(form.initial["issues_read"])
        self.assertFalse(form.initial.get("issues_triage"))
        self.assertFalse(form.initial.get("teams_read"))

    def test_unregistered_redirect_shows_error_page(self):
        response = self.client.get(self.url(redirect_uri="http://localhost:5555/other"))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.has_header("Location"))

    def test_missing_challenge_redirects_with_error(self):
        for challenge in ["", "too-short", "x" * 129]:
            query = self.query_of(self.client.get(self.url(code_challenge=challenge)))
            self.assertEqual(query["error"], "invalid_request")
            self.assertEqual(query["state"], "xyz")

    def test_allow_creates_code(self):
        response = self.client.post(self.url(), {
            "description": "Claude Code (MCP)", "project": "", "issues_read": "on", "events_read": "on"})
        query = self.query_of(response)
        code = OAuthAuthorizationCode.objects.get()
        self.assertEqual(query["code"], code.code)
        self.assertEqual(query["state"], "xyz")
        self.assertEqual(code.redirect_uri, CALLBACK)
        self.assertEqual(code.capabilities, ["events:read", "issues:read"])
        self.assertEqual(code.user, self.user)

    def test_superuser_gets_user_bound_code_without_unoffered_capabilities(self):
        superuser = get_user_model().objects.create_superuser(username="root", password="x")
        browser = Client()
        browser.force_login(superuser)
        response = browser.post(self.url(), {
            "description": "Claude Code (MCP)", "project": "", "issues_read": "on", "issues_delete": "on"})
        self.query_of(response)
        code = OAuthAuthorizationCode.objects.get()
        self.assertEqual(code.user, superuser)
        self.assertEqual(code.capabilities, ["issues:read"])

    def test_allow_with_project_binding_and_defaults(self):
        project = Project.objects.create(name="Web")
        ProjectMembership.objects.create(project=project, user=self.user, accepted=True)
        response = self.client.post(self.url(), {
            "description": "Claude Code (MCP)", "project": str(project.id), "projects_read": "on",
            "issues_read": "on", "events_read": "on", "issues_comment": "on"})
        self.query_of(response)
        self.assertEqual(OAuthAuthorizationCode.objects.get().project, project)

    def test_deny(self):
        query = self.query_of(self.client.post(self.url(), {"deny": "1"}))
        self.assertEqual(query["error"], "access_denied")
        self.assertFalse(OAuthAuthorizationCode.objects.exists())

    def test_cursor_app_callback(self):
        cursor_callback = "cursor://anysphere.cursor-mcp/oauth/callback"
        client_id = sign_client("Cursor", [cursor_callback, "http://localhost:8787/callback"])
        response = self.client.post(self.url(client_id=client_id, redirect_uri=cursor_callback), {
            "description": "Cursor (MCP)", "project": "", "issues_read": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(cursor_callback + "?code="))

    def test_claude_connector_callback(self):
        claude_callback = "https://claude.ai/api/mcp/auth_callback"
        client_id = sign_client("Claude", [claude_callback])
        response = self.client.post(self.url(client_id=client_id, redirect_uri=claude_callback), {
            "description": "Claude (MCP)", "project": "", "issues_read": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(claude_callback + "?code="))
