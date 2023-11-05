from django.shortcuts import render

from .models import Issue


def issue_list(request, project_id):
    issue_list = Issue.objects.filter(project_id=project_id)

    return render(request, "issues/issue_list.html", {
        "project_id": project_id,
        "issue_list": issue_list,
    })


def issue_event_list(request, issue_pk):
    issue = Issue.objects.get(pk=issue_pk)

    # note: once we have "Event" (with parsed info) we'll point straight to Issue from there which reduces the nr of
    # tables this join goes through by 1.
    event_list = issue.events.all()

    return render(request, "issues/issue_event_list.html", {
        "issue": issue,
        "event_list": event_list,
    })
