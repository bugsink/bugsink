import json

from django.test import RequestFactory
from django.urls import NoReverseMatch, resolve, reverse

from bugsink.period_utils import DATEUTIL_KWARGS_MAP

MAX_TEXT = 60_000

LIMIT = {"type": "integer", "minimum": 1, "maximum": 250, "default": 20, "description": "Page size."}
CURSOR = {"type": "string", "description": "The `cursor` query value of the previous response's `next` URL."}
ISSUE = {"type": "string", "description": "Issue UUID or friendly ID such as PROJ-123."}
EVENT = {"type": "string", "description": "Bugsink event UUID (the `id` field, not the SDK event_id)."}
PROJECT = {"type": "integer", "description": "Project ID."}

TOOLS = [
    {
        "name": "list_projects",
        "description": "List the projects you can see, including their DSN.",
        "capabilities": ["projects:read"], "hint": "read",
        "method": "GET", "url": "api:project-list",
        "properties": {"limit": LIMIT, "cursor": CURSOR},
    },
    {
        "name": "get_project",
        "description": "Get one project, including its DSN.",
        "capabilities": ["projects:read"], "hint": "read",
        "method": "GET", "url": "api:project-detail", "path": {"pk": "project"},
        "properties": {"project": PROJECT}, "required": ["project"],
    },
    {
        "name": "create_project",
        "description": "Create a project in a team (see list_teams). Returns the project including its DSN.",
        "capabilities": ["projects:manage", "projects:read"], "hint": "destructive",
        "method": "POST", "url": "api:project-list",
        "properties": {"team": {"type": "string", "description": "Team ID from list_teams."},
                       "name": {"type": "string"}},
        "required": ["team", "name"],
    },
    {
        "name": "list_teams",
        "description": "List the teams you can see.",
        "capabilities": ["teams:read"], "hint": "read",
        "method": "GET", "url": "api:team-list",
        "properties": {"limit": LIMIT, "cursor": CURSOR},
    },
    {
        "name": "list_issues",
        "description": "List issues. Defaults to open issues, most recently seen first. "
                       "`q` searches like the Bugsink UI, e.g. `TypeError environment:production`.",
        "capabilities": ["issues:read"], "hint": "read",
        "method": "GET", "url": "api:issue-list",
        "properties": {
            "project": PROJECT,
            "q": {"type": "string", "description": "Search query."},
            "state": {"type": "string", "enum": ["open", "unresolved", "resolved", "muted", "all"], "default": "open"},
            "sort": {"type": "string", "enum": ["last_seen", "digested_event_count", "digest_order"],
                     "default": "last_seen"},
            "order": {"type": "string", "enum": ["desc", "asc"], "default": "desc"},
            "limit": LIMIT, "cursor": CURSOR,
        },
    },
    {
        "name": "get_issue",
        "description": "Get one issue: title, state, first/last seen, event count.",
        "capabilities": ["issues:read"], "hint": "read",
        "method": "GET", "url": "api:issue-detail", "path": {"pk": "issue"},
        "properties": {"issue": ISSUE}, "required": ["issue"],
    },
    {
        "name": "get_issue_tags",
        "description": "Tag values and counts for an issue (environment, release, browser, ...).",
        "capabilities": ["events:read"], "hint": "read",
        "method": "GET", "url": "api:issue-tags", "path": {"pk": "issue"},
        "properties": {"issue": ISSUE, "key": {"type": "string", "description": "Only this tag key."},
                       "limit": LIMIT, "cursor": CURSOR},
        "required": ["issue"],
    },
    {
        "name": "list_events",
        "description": "List events of an issue, newest first. `limit=1` gives the latest event.",
        "capabilities": ["events:read"], "hint": "read",
        "method": "GET", "url": "api:event-list",
        "properties": {"issue": ISSUE, "limit": LIMIT, "cursor": CURSOR}, "required": ["issue"],
    },
    {
        "name": "get_event",
        "description": "Get one event's full data (request, breadcrumbs, contexts, tags). "
                       "Use get_event_stacktrace for the stacktrace.",
        "capabilities": ["events:read"], "hint": "read",
        "method": "GET", "url": "api:event-detail", "path": {"pk": "event"},
        "properties": {"event": EVENT}, "required": ["event"],
    },
    {
        "name": "get_event_stacktrace",
        "description": "An event's stacktrace as Markdown, with source context and local variables.",
        "capabilities": ["events:read"], "hint": "read",
        "method": "GET", "url": "api:event-stacktrace", "path": {"pk": "event"},
        "properties": {"event": EVENT,
                       "in_app_only": {"type": "boolean", "default": True,
                                       "description": "Only frames from the application's own code."}},
        "required": ["event"],
    },
    {
        "name": "lookup_event",
        "description": "Find an event by the event_id the SDK reported (e.g. from a log line or user report).",
        "capabilities": ["events:read"], "hint": "read",
        "method": "GET", "url": "api:event-lookup",
        "properties": {"project": PROJECT, "event_id": {"type": "string", "description": "SDK event ID."}},
        "required": ["project", "event_id"],
    },
    {
        "name": "comment_issue",
        "description": "Add a comment to an issue, e.g. a fix summary with the commit hash.",
        "capabilities": ["issues:comment"], "hint": "write",
        "method": "POST", "url": "api:issue-comment-list",
        "properties": {"issue": ISSUE, "comment": {"type": "string"}}, "required": ["issue", "comment"],
    },
    {
        "name": "resolve_issue",
        "description": "Mark an issue as resolved. `next_release`: resolved by the next release (use after "
                       "committing a fix); `latest_release`: already fixed in the latest release; `now`: resolved.",
        "capabilities": ["issues:triage"], "hint": "destructive",
        "method": "POST",
        "url": {"next_release": "api:issue-resolve-next", "latest_release": "api:issue-resolve-latest",
                "now": "api:issue-resolve"},
        "path": {"pk": "issue"},
        "properties": {"issue": ISSUE, "mode": {"type": "string", "enum": ["next_release", "latest_release", "now"],
                                                "default": "next_release"}},
        "required": ["issue"],
    },
    {
        "name": "reopen_issue",
        "description": "Reopen a resolved issue.",
        "capabilities": ["issues:triage"], "hint": "destructive",
        "method": "POST", "url": "api:issue-reopen", "path": {"pk": "issue"},
        "properties": {"issue": ISSUE}, "required": ["issue"],
    },
    {
        "name": "mute_issue",
        "description": "Mute an issue: `forever`; `for_period` (period_name + nr_of_periods); or "
                       "`until_threshold` (more than gte_threshold events per nr_of_periods period_name).",
        "capabilities": ["issues:triage"], "hint": "destructive",
        "method": "POST",
        "url": {"forever": "api:issue-mute", "for_period": "api:issue-mute-for",
                "until_threshold": "api:issue-mute-until"},
        "path": {"pk": "issue"},
        "properties": {
            "issue": ISSUE,
            "mode": {"type": "string", "enum": ["forever", "for_period", "until_threshold"], "default": "forever"},
            "period_name": {"type": "string", "enum": list(DATEUTIL_KWARGS_MAP)},
            "nr_of_periods": {"type": "integer", "minimum": 1},
            "gte_threshold": {"type": "integer", "minimum": 1},
        },
        "required": ["issue"],
    },
    {
        "name": "unmute_issue",
        "description": "Unmute a muted issue.",
        "capabilities": ["issues:triage"], "hint": "destructive",
        "method": "POST", "url": "api:issue-unmute", "path": {"pk": "issue"},
        "properties": {"issue": ISSUE}, "required": ["issue"],
    },
]

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}

_factory = RequestFactory()


class InvalidParams(Exception):
    pass


def tools_for(token):
    return [tool for tool in TOOLS if set(tool["capabilities"]) <= token.capabilities]


def tool_definition(tool):
    return {
        "name": tool["name"],
        "description": tool["description"],
        "inputSchema": {"type": "object", "properties": tool["properties"],
                        "required": tool.get("required", []), "additionalProperties": False},
        "annotations": {"readOnlyHint": tool["hint"] == "read", "destructiveHint": tool["hint"] == "destructive"},
    }


def _validated_arguments(tool, arguments):
    # agents send null for optional arguments; treat it as "not given"
    arguments = {name: value for name, value in arguments.items() if value is not None}
    unknown = set(arguments) - set(tool["properties"])
    if unknown:
        raise InvalidParams("Unknown arguments: %s." % ", ".join(sorted(unknown)))
    missing = [name for name in tool.get("required", []) if name not in arguments]
    if missing:
        raise InvalidParams("Missing arguments: %s." % ", ".join(missing))

    args = {name: schema["default"] for name, schema in tool["properties"].items() if "default" in schema}
    args.update(arguments)
    for name, value in args.items():
        enum = tool["properties"][name].get("enum")
        if enum is not None and value not in enum:
            raise InvalidParams("%s must be one of: %s." % (name, ", ".join(enum)))
    return args


def _dispatch(request, token, tool, args):
    url_name = tool["url"][args.pop("mode")] if isinstance(tool["url"], dict) else tool["url"]
    path_kwargs = {kwarg: str(args.pop(arg)) for kwarg, arg in tool.get("path", {}).items()}
    try:
        path = reverse(url_name, kwargs=path_kwargs)
    except NoReverseMatch:
        raise InvalidParams("Invalid identifier.")

    headers = {"HTTP_AUTHORIZATION": f"Bearer {token.token}", "HTTP_HOST": request.get_host()}
    if tool["method"] == "GET":
        query = {name: str(value).lower() if isinstance(value, bool) else value for name, value in args.items()}
        inner = _factory.get(path, query, secure=request.is_secure(), **headers)
    else:
        inner = _factory.post(path, json.dumps(args), content_type="application/json",
                              secure=request.is_secure(), **headers)

    match = resolve(path)
    if match.view_name != url_name:  # e.g. get_event(event="lookup") resolves to /events/lookup/
        raise InvalidParams("Invalid identifier.")
    # never render: MarkdownRenderer turns errors into HTML, and response.data is what we want anyway
    response = match.func(inner, *match.args, **match.kwargs)
    return response.status_code, response.data


def result_text(status, data):
    text = data if isinstance(data, str) else json.dumps(data, default=str)
    is_error = not 200 <= status < 300
    if is_error:
        text = f"HTTP {status}: {text}"
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n[truncated]"
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(request, token, name, arguments):
    tool = TOOLS_BY_NAME.get(name) if isinstance(name, str) else None
    if tool is None:
        raise InvalidParams(f"Unknown tool: {name}.")

    status, data = _dispatch(request, token, tool, _validated_arguments(tool, arguments))
    if name == "create_project" and status == 201:
        status, data = _dispatch(request, token, TOOLS_BY_NAME["get_project"], {"project": data["id"]})
    if name == "get_event" and status == 200:
        data.pop("stacktrace_md", None)
    return result_text(status, data)
