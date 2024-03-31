from collections import namedtuple
import json

from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.http import HttpResponseRedirect

from events.models import Event
from bugsink.decorators import project_membership_required, issue_membership_required

from .utils import get_issue_grouper_for_data
from .models import Issue, IssueQuerysetStateManager, IssueStateManager


MuteOption = namedtuple("MuteOption", ["for_or_until", "period_name", "nr_of_periods", "gte_threshold"])

# I imagine that we may make this configurable at the installation, organization and/or project level, but for now we
# just have a global constant.
GLOBAL_MUTE_OPTIONS = [
    MuteOption("for", "day", 1, None),
    MuteOption("for", "week", 1, None),
    MuteOption("for", "month", 1, None),
    MuteOption("for", "month", 3, None),

    MuteOption("until", "hour", 1, 5),
    MuteOption("until", "hour", 24, 5),
    MuteOption("until", "hour", 24, 100),
]


def _is_valid_action(action, issue):
    """We take the 'strict' approach of complaining even when the action is simply a no-op, because you're already in
    the desired state."""

    if issue.is_resolved:
        # any action is illegal on resolved issues (as per our current UI)
        return False

    if action.startswith("resolved_release:"):
        release_version = action.split(":", 1)[1]
        if issue.events_at.contains(release_version + "\n"):
            return False

    elif action.startswith("mute"):
        if issue.is_muted:
            return False

    elif action == "unmute":
        if not issue.is_muted:
            return False

    return True


def _q_for_invalid_for_action(action):
    """returns a Q obj of issues for which the action is not valid."""

    illegal_conditions = Q(is_resolved=True)  # any action is illegal on resolved issues (as per our current UI)

    if action.startswith("resolved_release:"):
        release_version = action.split(":", 1)[1]
        illegal_conditions = illegal_conditions | Q(events_at__contains=release_version + "\n")

    elif action.startswith("mute"):
        illegal_conditions = illegal_conditions | Q(is_muted=True)

    elif action == "unmute":
        illegal_conditions = illegal_conditions | Q(is_muted=False)

    return illegal_conditions


def _apply_action(manager, issue_or_qs, action):
    if action == "resolve":
        manager.resolve(issue_or_qs)
    elif action.startswith("resolved_release:"):
        release_version = action.split(":", 1)[1]
        manager.resolve_by_release(issue_or_qs, release_version)
    elif action == "resolved_next":
        manager.resolve_by_next(issue_or_qs)
    # elif action == "reopen":  # not allowed from the UI
    #     manager.reopen(issue_or_qs)
    elif action == "mute":
        manager.mute(issue_or_qs)
    elif action.startswith("mute_for:"):
        mute_for_params = action.split(":", 1)[1]
        period_name, nr_of_periods, _ = mute_for_params.split(",")
        manager.mute(issue_or_qs, unmute_after_tuple=(int(nr_of_periods), period_name))

    elif action.startswith("mute_until:"):
        mute_for_params = action.split(":", 1)[1]
        period_name, nr_of_periods, gte_threshold = mute_for_params.split(",")

        manager.mute(issue_or_qs, json.dumps([{
            "period": period_name,
            "nr_of_periods": int(nr_of_periods),
            "volume": int(gte_threshold),
        }]))
    elif action == "unmute":
        manager.unmute(issue_or_qs)


@project_membership_required
def issue_list(request, project, state_filter="open"):
    if request.method == "POST":
        issue_ids = request.POST.getlist('issue_ids[]')
        issue_qs = Issue.objects.filter(pk__in=issue_ids)
        illegal_conditions = _q_for_invalid_for_action(request.POST["action"])
        # list() is necessary because we need to evaluate the qs before any actions are actually applied (if we don't,
        # actions are always marked as illegal, because they are applied first, then checked (and applying twice is
        # illegal)
        unapplied_issue_ids = list(issue_qs.filter(illegal_conditions).values_list("id", flat=True))
        _apply_action(IssueQuerysetStateManager, issue_qs.exclude(illegal_conditions), request.POST["action"])

    else:
        unapplied_issue_ids = None

    d_state_filter = {
        "open": lambda qs: qs.filter(is_resolved=False, is_muted=False),
        "unresolved": lambda qs: qs.filter(is_resolved=False),
        "resolved": lambda qs: qs.filter(is_resolved=True),
        "muted": lambda qs: qs.filter(is_muted=True),
        "all": lambda qs: qs,
    }

    issue_list = d_state_filter[state_filter](
        Issue.objects.filter(project=project)
    ).order_by("-last_seen")

    return render(request, "issues/issue_list.html", {
        "project": project,
        "issue_list": issue_list,
        "state_filter": state_filter,
        "mute_options": GLOBAL_MUTE_OPTIONS,

        "unapplied_issue_ids": unapplied_issue_ids,

        # design decision: we statically determine some disabledness (i.e. choices that will never make sense are
        # disallowed), but we don't have any dynamic disabling based on the selected issues.
        "disable_resolve_buttons": state_filter in ("resolved"),
        "disable_mute_buttons": state_filter in ("resolved", "muted"),
        "disable_unmute_buttons": state_filter in ("resolved", "open"),
    })


@issue_membership_required
def issue_last_event(request, issue):
    last_event = issue.event_set.order_by("timestamp").last()

    return redirect(issue_event_stacktrace, issue_pk=issue.pk, event_pk=last_event.pk)


def _handle_post(request, issue):
    if _is_valid_action(request.POST["action"], issue):
        _apply_action(IssueStateManager, issue, request.POST["action"])
        issue.save()

    # note that if the action is not valid, we just ignore it (i.e. we don't show any error message or anything)
    # this is probably what you want, because the most common case of action-not-valid is 'it already happened
    # through some other UI path'. The only case I can think of where this is not the case is where you try to
    # resolve an issue for a specific release, and while you where thinking about that, it occurred for that
    # release. In that case it will probably stand out that your buttons don't become greyed out, and that the
    # dropdown no longer functions.
    return HttpResponseRedirect(request.path_info)


@issue_membership_required
def issue_event_stacktrace(request, issue, event_pk):
    if request.method == "POST":
        return _handle_post(request, issue)

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

    return render(request, "issues/issue_stacktrace.html", {
        "tab": "stacktrace",
        "project": issue.project,
        "issue": issue,
        "event": event,
        "is_event_page": True,
        "parsed_data": parsed_data,
        "exceptions": exceptions,
        "issue_grouper": get_issue_grouper_for_data(parsed_data),
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@issue_membership_required
def issue_event_breadcrumbs(request, issue, event_pk):
    if request.method == "POST":
        return _handle_post(request, issue)

    event = get_object_or_404(Event, pk=event_pk)

    parsed_data = json.loads(event.data)

    return render(request, "issues/issue_breadcrumbs.html", {
        "tab": "breadcrumbs",
        "project": issue.project,
        "issue": issue,
        "event": event,
        "is_event_page": True,
        "parsed_data": parsed_data,
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@issue_membership_required
def issue_event_details(request, issue, event_pk):
    if request.method == "POST":
        return _handle_post(request, issue)

    event = get_object_or_404(Event, pk=event_pk)

    return render(request, "issues/issue_event_details.html", {
        "tab": "event-details",
        "project": issue.project,
        "issue": issue,
        "event": event,
        "is_event_page": True,
    })


@issue_membership_required
def issue_history(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    return render(request, "issues/issue_history.html", {
        "tab": "history",
        "project": issue.project,
        "issue": issue,
        "event": issue.event_set.order_by("timestamp").last(),  # the template needs this for the tabs, we pick the last
        "is_event_page": False,
    })


@issue_membership_required
def issue_grouping(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    return render(request, "issues/issue_grouping.html", {
        "tab": "grouping",
        "project": issue.project,
        "issue": issue,
        "event": issue.event_set.order_by("timestamp").last(),  # the template needs this for the tabs, we pick the last
        "is_event_page": False,
    })


@issue_membership_required
def issue_event_list(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    event_list = issue.event_set.all()

    return render(request, "issues/issue_event_list.html", {
        "tab": "event-list",
        "project": issue.project,
        "issue": issue,
        "event": issue.event_set.order_by("timestamp").last(),  # the template needs this for the tabs, we pick the last
        "event_list": event_list,
        "is_event_page": False,
    })
