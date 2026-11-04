import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from bsmain.models import AuthToken
from bugsink.api_capabilities import get_token_guard
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from events.factories import create_event
from issues.factories import get_or_create_issue
from mcpserver.tools import TOOLS, InvalidParams, call_tool, result_text, tool_definition, tools_for
from projects.models import ProjectMembership
from teams.models import Team


class ToolTableTests(SimpleTestCase):
    def test_capabilities_match_token_guards(self):
        for tool in TOOLS:
            urls = tool["url"].values() if isinstance(tool["url"], dict) else [tool["url"]]
            for url_name in urls:
                match = resolve(reverse(url_name, kwargs={kwarg: "x" for kwarg in tool.get("path", {})}))
                action = match.func.actions[tool["method"].lower()]
                guard = get_token_guard(getattr(match.func.cls, action))
                self.assertIn(guard.capability, tool["capabilities"], tool["name"])

    def test_tools_for_filters_by_capability(self):
        names = {tool["name"] for tool in tools_for(AuthToken(issues_read=True))}
        self.assertIn("list_issues", names)
        self.assertIn("get_issue", names)
        self.assertNotIn("get_event_stacktrace", names)
        self.assertNotIn("resolve_issue", names)

    def test_annotations(self):
        definitions = {tool["name"]: tool_definition(tool) for tool in TOOLS}
        self.assertEqual(definitions["get_issue"]["annotations"], {"readOnlyHint": True, "destructiveHint": False})
        self.assertEqual(definitions["resolve_issue"]["annotations"], {"readOnlyHint": False, "destructiveHint": True})
        self.assertEqual(definitions["comment_issue"]["annotations"], {"readOnlyHint": False, "destructiveHint": False})

    def test_long_text_is_truncated(self):
        text = result_text(200, "x" * 70_000)["content"][0]["text"]
        self.assertTrue(text.endswith("[truncated]"))
        self.assertLess(len(text), 61_000)


class CallToolTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="alice")
        self.issue, _ = get_or_create_issue()
        ProjectMembership.objects.create(project=self.issue.project, user=self.user, accepted=True)
        self.token = AuthToken.objects.create(
            is_user_bound=True, user=self.user, issues_read=True, events_read=True, projects_read=True)
        self.request = RequestFactory().post("/mcp")

    def call(self, name, arguments, token=None):
        return call_tool(self.request, token or self.token, name, arguments)

    def test_get_issue(self):
        result = self.call("get_issue", {"issue": self.issue.friendly_id()})
        self.assertFalse(result["isError"])
        self.assertIn(str(self.issue.id), result["content"][0]["text"])

    def test_foreign_project_is_an_error_result(self):
        other, _ = get_or_create_issue()
        result = self.call("get_issue", {"issue": str(other.id)})
        self.assertTrue(result["isError"])
        self.assertTrue(result["content"][0]["text"].startswith("HTTP 403"))

    def test_invalid_params(self):
        for name, arguments in [
                ("no_such_tool", {}),
                (["not", "a", "name"], {}),
                ("get_issue", {}),
                ("get_issue", {"issue": None}),
                ("get_event", {"event": "lookup"}),
                ("get_issue", {"issue": "x", "bogus": 1}),
                ("resolve_issue", {"issue": "x", "mode": "someday"})]:
            with self.assertRaises(InvalidParams, msg=name):
                self.call(name, arguments)

    def test_null_optional_arguments_use_defaults(self):
        result = self.call("list_issues", {"q": None, "project": None, "cursor": None})
        self.assertFalse(result["isError"], result)

    def test_get_event_drops_stacktrace_md(self):
        event = create_event(issue=self.issue)
        data = json.loads(self.call("get_event", {"event": str(event.id)})["content"][0]["text"])
        self.assertEqual(data["id"], str(event.id))
        self.assertNotIn("stacktrace_md", data)

    def test_create_project_returns_dsn(self):
        superuser = get_user_model().objects.create_superuser(username="root", password="x")
        token = AuthToken.objects.create(is_user_bound=True, user=superuser, projects_manage=True, projects_read=True)
        team = Team.objects.create(name="Core")
        result = self.call("create_project", {"team": str(team.id), "name": "web"}, token=token)
        self.assertFalse(result["isError"], result)
        self.assertIn("dsn", json.loads(result["content"][0]["text"]))
