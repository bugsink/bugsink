import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from bsmain.models import AuthToken
from bugsink.app_settings import get_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from events.factories import create_event
from issues.factories import get_or_create_issue
from mcpserver.models import McpToolCall
from projects.models import ProjectMembership


class McpEndpointTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="alice")
        self.issue, _ = get_or_create_issue()
        ProjectMembership.objects.create(project=self.issue.project, user=self.user, accepted=True)
        self.token = AuthToken.objects.create(is_user_bound=True, user=self.user, issues_read=True, events_read=True)
        self.client = Client(enforce_csrf_checks=True)

    def post(self, body, token=None, path="/mcp", **extra):
        token = token or self.token
        if not isinstance(body, str):
            body = json.dumps(body)
        return self.client.post(path, body, content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {token.token}", **extra)

    def rpc(self, method, params=None):
        response = self.post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_unauthenticated_gets_401_with_metadata_pointer(self):
        for path in ["/mcp", "/mcp/"]:
            response = self.client.post(path, "{}", content_type="application/json")
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(
                response["WWW-Authenticate"],
                f'Bearer resource_metadata="{get_settings().BASE_URL}/.well-known/oauth-protected-resource/mcp"')

    def test_service_token_forbidden(self):
        service_token = AuthToken.objects.create(issues_read=True)
        response = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=service_token)
        self.assertEqual(response.status_code, 403)

    def test_foreign_origin_forbidden(self):
        response = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, HTTP_ORIGIN="https://evil.com")
        self.assertEqual(response.status_code, 403)

    def test_claude_origin_allowed(self):
        response = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, HTTP_ORIGIN="https://claude.ai")
        self.assertEqual(response.status_code, 200)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/mcp").status_code, 405)

    def test_protocol_errors(self):
        self.assertEqual(self.post("not json").json()["error"]["code"], -32700)
        self.assertEqual(self.post([{"jsonrpc": "2.0", "id": 1, "method": "ping"}]).json()["error"]["code"], -32600)
        self.assertEqual(self.rpc("nope")["error"]["code"], -32601)
        self.assertEqual(self.rpc("tools/call", {"name": "get_issue", "arguments": {}})["error"]["code"], -32602)

    def test_notification_gets_202(self):
        response = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((response.status_code, response.content), (202, b""))

    def test_initialize(self):
        result = self.rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertIn("untrusted", result["instructions"])
        self.assertEqual(self.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"],
                         "2025-11-25")

    def test_tools_list_and_call(self):
        names = {tool["name"] for tool in self.rpc("tools/list")["result"]["tools"]}
        self.assertIn("get_event_stacktrace", names)
        self.assertNotIn("resolve_issue", names)

        event = create_event(issue=self.issue)
        result = self.rpc("tools/call", {"name": "get_event_stacktrace", "arguments": {"event": str(event.id)}})
        self.assertFalse(result["result"]["isError"])

    def test_tool_calls_are_logged(self):
        self.token.description = "Claude Code (MCP)"
        self.token.save()
        event = create_event(issue=self.issue)
        self.rpc("tools/call", {"name": "get_event_stacktrace", "arguments": {"event": str(event.id)}})
        self.rpc("tools/call", {"name": "resolve_issue", "arguments": {"issue": str(self.issue.id)}})
        self.rpc("tools/call", {"name": "get_issue", "arguments": {}})

        ok, forbidden, invalid = McpToolCall.objects.order_by("id")
        self.assertEqual((ok.tool, ok.user, ok.client_name, ok.error),
                         ("get_event_stacktrace", self.user, "Claude Code (MCP)", ""))
        self.assertEqual(ok.arguments, {"event": str(event.id)})
        self.assertTrue(forbidden.error.startswith("HTTP 403"))
        self.assertEqual(invalid.error, "Missing arguments: issue.")

    def test_old_log_entries_are_removed(self):
        old = McpToolCall.objects.create(user=self.user, client_name="x", tool="get_issue", arguments={})
        McpToolCall.objects.filter(pk=old.pk).update(timestamp=timezone.now() - timedelta(days=31))
        self.rpc("tools/call", {"name": "list_issues", "arguments": {}})
        self.assertEqual(list(McpToolCall.objects.values_list("tool", flat=True)), ["list_issues"])
