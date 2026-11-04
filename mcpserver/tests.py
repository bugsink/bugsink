import json
from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth import get_user_model
from django.test import Client

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from events.factories import create_event
from issues.factories import get_or_create_issue
from issues.models import TurningPoint, TurningPointKind
from mcpserver.models import OAuthGrant
from projects.models import ProjectMembership

VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class OAuthMcpFlowTests(TransactionTestCase):
    def test_agent_connects_works_and_is_disconnected(self):
        user = get_user_model().objects.create_user(username="alice")
        issue, _ = get_or_create_issue()
        event = create_event(issue=issue)
        ProjectMembership.objects.create(project=issue.project, user=user, accepted=True)

        agent = Client(enforce_csrf_checks=True)
        browser = Client()
        browser.force_login(user)

        self.assertEqual(agent.post("/mcp", "{}", content_type="application/json").status_code, 401)
        metadata = agent.get("/.well-known/oauth-authorization-server").json()
        self.assertIn("/oauth/token", metadata["token_endpoint"])

        registration = agent.post("/oauth/register", json.dumps(
            {"client_name": "Claude Code", "redirect_uris": ["http://localhost:1234/callback"]}),
            content_type="application/json").json()

        callback = "http://localhost:4321/callback"
        authorize_url = "/oauth/authorize?" + urlencode({
            "response_type": "code", "client_id": registration["client_id"], "redirect_uri": callback,
            "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "s1"})
        self.assertEqual(browser.get(authorize_url).status_code, 200)
        consent = browser.post(authorize_url, {
            "description": "Claude Code (MCP)", "project": "", "projects_read": "on", "issues_read": "on",
            "events_read": "on", "issues_comment": "on", "issues_triage": "on"})
        code = parse_qs(urlsplit(consent["Location"]).query)["code"][0]

        tokens = agent.post("/oauth/token", {
            "grant_type": "authorization_code", "code": code, "client_id": registration["client_id"],
            "redirect_uri": callback, "code_verifier": VERIFIER}).json()

        def rpc(access_token, method, params=None):
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
            return agent.post("/mcp", body, content_type="application/json",
                              HTTP_AUTHORIZATION=f"Bearer {access_token}")

        self.assertEqual(rpc(tokens["access_token"], "initialize").json()["result"]["serverInfo"]["name"], "bugsink")
        names = {tool["name"] for tool in rpc(tokens["access_token"], "tools/list").json()["result"]["tools"]}
        self.assertTrue({"get_event_stacktrace", "comment_issue"} <= names)

        stacktrace = rpc(tokens["access_token"], "tools/call", {
            "name": "get_event_stacktrace", "arguments": {"event": str(event.id)}}).json()["result"]
        self.assertFalse(stacktrace["isError"])

        comment = rpc(tokens["access_token"], "tools/call", {
            "name": "comment_issue", "arguments": {"issue": str(issue.id), "comment": "Fixed in abc123"}})
        self.assertFalse(comment.json()["result"]["isError"])
        self.assertEqual(TurningPoint.objects.get(kind=TurningPointKind.MANUAL_ANNOTATION).user, user)

        resolved = rpc(tokens["access_token"], "tools/call", {
            "name": "resolve_issue", "arguments": {"issue": str(issue.id), "mode": "now"}})
        self.assertFalse(resolved.json()["result"]["isError"], resolved.json())
        self.assertEqual(TurningPoint.objects.get(kind=TurningPointKind.RESOLVED).user, user)

        refreshed = agent.post("/oauth/token", {
            "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}).json()
        self.assertEqual(rpc(tokens["access_token"], "ping").status_code, 401)
        self.assertEqual(rpc(refreshed["access_token"], "ping").status_code, 200)

        browser.post("/oauth/connections/", {"disconnect": OAuthGrant.objects.get().pk})
        self.assertEqual(rpc(refreshed["access_token"], "ping").status_code, 401)
