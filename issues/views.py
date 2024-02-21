import json
from django.shortcuts import render, get_object_or_404, redirect

from events.models import Event

from projects.models import Project

from .utils import get_issue_grouper_for_data
from .models import Issue, IssueStateManager


def issue_list(request, project_id, state_filter="unresolved"):
    if request.method == "POST":
        issue_ids = request.POST.getlist('issue_ids[]')
        raise NotImplementedError("TODO: bulk actions")

    d_state_filter = {
        "unresolved": lambda qs: qs.filter(is_resolved=False),
        "resolved": lambda qs: qs.filter(is_resolved=True),
        "muted": lambda qs: qs.filter(is_muted=True),
        "all": lambda qs: qs,
    }

    issue_list = d_state_filter[state_filter](
        Issue.objects.filter(project_id=project_id)
    ).order_by("-last_seen")

    project = get_object_or_404(Project, pk=project_id)

    return render(request, "issues/issue_list.html", {
        "project": project,
        "issue_list": issue_list,
        "state_filter": state_filter,
    })


def issue_last_event(request, issue_pk):
    issue = get_object_or_404(Issue, pk=issue_pk)
    last_event = issue.event_set.order_by("timestamp").last()

    return redirect(issue_event_detail, issue_pk=issue_pk, event_pk=last_event.pk)


def issue_event_detail(request, issue_pk, event_pk):
    issue = get_object_or_404(Issue, pk=issue_pk)

    if request.method == "POST":
        if request.POST["action"] == "resolved":
            IssueStateManager.resolve(issue)
        elif request.POST["action"].startswith("resolved_release:"):
            release_version = request.POST["action"].split(":", 1)[1]
            IssueStateManager.resolve_by_release(issue, release_version)
        elif request.POST["action"] == "resolved_next":
            IssueStateManager.resolve_by_next(issue)
        elif request.POST["action"] == "reopen":
            IssueStateManager.reopen(issue)

        elif request.POST["action"] == "mute":
            ...

        issue.save()
        return redirect(issue_event_detail, issue_pk=issue_pk, event_pk=event_pk)

    event = get_object_or_404(Event, pk=event_pk)

    parsed_data = json.loads(event.data)

    # sentry/glitchtip have some code here to deal with the case that "values" is not present, and exception itself is
    # the list of exceptions, but we don't aim for endless backwards compat (yet) so we don't.
    exceptions = parsed_data["exception"]["values"] if "exception" in parsed_data else None

    if "logentry" in parsed_data:
        logentry = parsed_data["logentry"]
        if "formatted" not in logentry:
            # TODO this is just a wild guess"
            if "message" in logentry:
                if "params" not in logentry:
                    logentry["formatted"] = logentry["message"]
                else:
                    logentry["formatted"] = logentry["message"].format(logentry["params"])

    return render(request, "issues/issue_detail.html", {
        "issue": issue,
        "event": event,
        "parsed_data": parsed_data,
        "exceptions": exceptions,
        "issue_grouper": get_issue_grouper_for_data(parsed_data),
    })


def issue_event_list(request, issue_pk):
    # TODO un-uglify, refactor the html somewhat.

    issue = Issue.objects.get(pk=issue_pk)

    # note: once we have "Event" (with parsed info) we'll point straight to Issue from there which reduces the nr of
    # tables this join goes through by 1.
    event_list = issue.events.all()

    return render(request, "issues/issue_event_list.html", {
        "issue": issue,
        "event_list": event_list,
    })
