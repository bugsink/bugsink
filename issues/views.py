from collections import namedtuple
import json

from django.utils import timezone
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.http import HttpResponseRedirect, HttpResponseNotAllowed
from django.utils.safestring import mark_safe
from django.template.defaultfilters import date
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.core.paginator import Paginator

from bugsink.decorators import project_membership_required, issue_membership_required, atomic_for_request_method
from bugsink.transaction import durable_atomic
from bugsink.period_utils import add_periods_to_datetime

from events.models import Event
from events.ua_stuff import enrich_contexts_with_ua

from compat.timestamp import format_timestamp
from projects.models import ProjectMembership

from .models import Issue, IssueQuerysetStateManager, IssueStateManager, TurningPoint, TurningPointKind
from .forms import CommentForm


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
        if release_version + "\n" in issue.events_at:
            return False

    elif action.startswith("mute"):
        if issue.is_muted:
            return False

        # TODO muting with a VBC that is already met should be invalid. See 'Exception("The unmute condition is already'

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


def _make_history(issue_or_qs, action, user):
    if action == "resolve":
        kind = TurningPointKind.RESOLVED
    elif action.startswith("resolved"):
        kind = TurningPointKind.RESOLVED
    elif action.startswith("mute"):
        kind = TurningPointKind.MUTED
    elif action == "unmute":
        kind = TurningPointKind.UNMUTED
    else:
        raise ValueError(f"unknown action: {action}")

    if action.startswith("mute_for:"):
        mute_for_params = action.split(":", 1)[1]
        period_name, nr_of_periods, _ = mute_for_params.split(",")
        unmute_after = add_periods_to_datetime(timezone.now(), int(nr_of_periods), period_name)
        metadata = {"mute_for": {
            "period_name": period_name, "nr_of_periods": int(nr_of_periods),
            "unmute_after": format_timestamp(unmute_after)}}

    elif action.startswith("mute_until:"):
        mute_for_params = action.split(":", 1)[1]
        period_name, nr_of_periods, gte_threshold = mute_for_params.split(",")
        metadata = {"mute_until": {
            "period_name": period_name, "nr_of_periods": int(nr_of_periods), "gte_threshold": gte_threshold}}

    elif action == "mute":
        metadata = {"mute_unconditionally": True}

    elif action.startswith("resolved_release:"):
        release_version = action.split(":", 1)[1]
        metadata = {"resolved_release": release_version}
    elif action == "resolved_next":
        metadata = {"resolve_by_next": True}
    elif action == "resolve":
        metadata = {"resolved_unconditionally": True}
    else:
        metadata = {}

    now = timezone.now()
    if isinstance(issue_or_qs, Issue):
        TurningPoint.objects.create(
            issue=issue_or_qs, kind=kind, user=user, metadata=json.dumps(metadata), timestamp=now)
    else:
        TurningPoint.objects.bulk_create([
            TurningPoint(issue=issue, kind=kind, user=user, metadata=json.dumps(metadata), timestamp=now)
            for issue in issue_or_qs
        ])


def _apply_action(manager, issue_or_qs, action, user):
    _make_history(issue_or_qs, action, user)

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
        unmute_after = add_periods_to_datetime(timezone.now(), int(nr_of_periods), period_name)
        manager.mute(issue_or_qs, unmute_after=unmute_after)

    elif action.startswith("mute_until:"):
        mute_for_params = action.split(":", 1)[1]
        period_name, nr_of_periods, gte_threshold = mute_for_params.split(",")

        manager.mute(issue_or_qs, unmute_on_volume_based_conditions=json.dumps([{
            "period": period_name,
            "nr_of_periods": int(nr_of_periods),
            "volume": int(gte_threshold),
        }]))
    elif action == "unmute":
        manager.unmute(issue_or_qs)


def issue_list(request, project_pk, state_filter="open"):
    # to keep the write lock as short as possible, issue_list is split up into 2 parts (read/write vs pure reading),
    # which take in the order of 5ms / 120ms respectively. Some info is passed between transactions (project and
    # unapplied_issue_ids), but since this is respectively sensitive to much change and the direct result of our own
    # current action, I don't think this can lead to surprising results.

    project, unapplied_issue_ids = _issue_list_pt_1(request, project_pk=project_pk, state_filter=state_filter)
    with durable_atomic():
        return _issue_list_pt_2(request, project, state_filter, unapplied_issue_ids)


@atomic_for_request_method
@project_membership_required
def _issue_list_pt_1(request, project, state_filter="open"):
    if request.method == "POST":
        issue_ids = request.POST.getlist('issue_ids[]')
        issue_qs = Issue.objects.filter(pk__in=issue_ids)
        illegal_conditions = _q_for_invalid_for_action(request.POST["action"])
        # list() is necessary because we need to evaluate the qs before any actions are actually applied (if we don't,
        # actions are always marked as illegal, because they are applied first, then checked (and applying twice is
        # illegal)
        unapplied_issue_ids = list(issue_qs.filter(illegal_conditions).values_list("id", flat=True))
        _apply_action(
            IssueQuerysetStateManager, issue_qs.exclude(illegal_conditions), request.POST["action"], request.user)

    else:
        unapplied_issue_ids = None

    return project, unapplied_issue_ids


def _issue_list_pt_2(request, project, state_filter, unapplied_issue_ids):
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

    # this is really TSTTCPW (or more like a "fake it till you make it" thing); but I'd rather "have something" and then
    # have really-good-search than to have either nothing at all, or half-baked search. Note that we didn't even bother
    # to set indexes on the fields we search on (nor create a single searchable field for the whole of 'title').
    if request.GET.get("q"):
        issue_list = issue_list.filter(
            Q(calculated_type__icontains=request.GET["q"]) | Q(calculated_value__icontains=request.GET["q"]))

    return render(request, "issues/issue_list.html", {
        "project": project,
        "member": ProjectMembership.objects.get(project=project, user=request.user),
        "issue_list": issue_list,
        "state_filter": state_filter,
        "mute_options": GLOBAL_MUTE_OPTIONS,

        "unapplied_issue_ids": unapplied_issue_ids,

        # design decision: we statically determine some disabledness (i.e. choices that will never make sense are
        # disallowed), but we don't have any dynamic disabling based on the selected issues.
        "disable_resolve_buttons": state_filter in ("resolved"),
        "disable_mute_buttons": state_filter in ("resolved", "muted"),
        "disable_unmute_buttons": state_filter in ("resolved", "open"),
        "q": request.GET.get("q", ""),
    })


def event_by_internal_id(request, event_pk):
    # a view that allows to link straight to an event by (internal) id. This comes with the cost of a bunch more queries
    # and a Http redirect when actually clicked, but has the advantage of not needing that event's issue id when
    # rendering the link. Note that no Auth is needed here because nothing is actually shown.
    event = get_object_or_404(Event, id=event_pk)
    issue = event.issue
    return redirect(issue_event_stacktrace, issue_pk=issue.pk, event_pk=event.pk)


def _handle_post(request, issue):
    if _is_valid_action(request.POST["action"], issue):
        _apply_action(IssueStateManager, issue, request.POST["action"], request.user)
        issue.save()

    # note that if the action is not valid, we just ignore it (i.e. we don't show any error message or anything)
    # this is probably what you want, because the most common case of action-not-valid is 'it already happened
    # through some other UI path'. The only case I can think of where this is not the case is where you try to
    # resolve an issue for a specific release, and while you where thinking about that, it occurred for that
    # release. In that case it will probably stand out that your buttons don't become greyed out, and that the
    # dropdown no longer functions. already-true-vbc-unmute may be another exception to this rule.
    return HttpResponseRedirect(request.path_info)


def _get_event(issue, event_pk, digest_order, nav):
    if nav is not None:
        if nav == "first":
            return Event.objects.filter(issue=issue).order_by("digest_order").first()
        if nav == "last":
            return Event.objects.filter(issue=issue).order_by("digest_order").last()

        if nav in ["prev", "next"]:
            if nav == "prev":
                result = Event.objects.filter(
                    issue=issue, digest_order__lt=digest_order).order_by("-digest_order").first()
            elif nav == "next":
                result = Event.objects.filter(
                    issue=issue, digest_order__gt=digest_order).order_by("digest_order").first()
            if result is None:
                raise Event.DoesNotExist
            return result

        raise Http404("Cannot look up with '%s'" % nav)

    if event_pk is not None:
        # we match on both internal and external id, trying internal first
        try:
            return Event.objects.get(pk=event_pk)
        except Event.DoesNotExist:
            return Event.objects.get(issue=issue, event_id=event_pk)

    elif digest_order is not None:
        return Event.objects.get(issue=issue, digest_order=digest_order)
    else:
        raise ValueError("either event_pk or digest_order must be provided")


@atomic_for_request_method
@issue_membership_required
def issue_event_stacktrace(request, issue, event_pk=None, digest_order=None, nav=None):
    if request.method == "POST":
        return _handle_post(request, issue)

    try:
        event = _get_event(issue, event_pk, digest_order, nav)
    except Event.DoesNotExist:
        return issue_event_404(request, issue, "stacktrace", "event_stacktrace")

    parsed_data = json.loads(event.data)

    # sentry/glitchtip have some code here to deal with the case that "values" is not present, and exception itself is
    # the list of exceptions, but we don't aim for endless backwards compat (yet) so we don't.
    exceptions = parsed_data["exception"]["values"] if "exception" in parsed_data else None

    # NOTE: I considered making this a clickable button of some sort, but decided against it in the end. Getting the UI
    # right is quite hard (https://ux.stackexchange.com/questions/1318) but more generally I would assume that having
    # your whole screen turned upside down is not something you do willy-nilly. Better to just have good defaults and
    # (possibly later) have this as something that is configurable at the user level.
    stack_of_plates = event.platform != "python"  # Python is the only platform that has chronological stacktraces

    if exceptions is not None and len(exceptions) > 0:
        if exceptions[-1].get('stacktrace') and exceptions[-1]['stacktrace'].get('frames'):
            exceptions[-1]['stacktrace']['frames'][-1]['raise_point'] = True

        if stack_of_plates:
            # NOTE manipulation of parsed_data going on here, this could be a trap if other parts depend on it
            # (e.g. grouper)
            exceptions = [e for e in reversed(exceptions)]
            for exception in exceptions:
                if not exception.get('stacktrace'):
                    continue
                exception['stacktrace']['frames'] = [f for f in reversed(exception['stacktrace']['frames'])]

    return render(request, "issues/stacktrace.html", {
        "tab": "stacktrace",
        "this_view": "event_stacktrace",
        "project": issue.project,
        "issue": issue,
        "event": event,
        "is_event_page": True,
        "parsed_data": parsed_data,
        "exceptions": exceptions,
        "stack_of_plates": stack_of_plates,
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


def issue_event_404(request, issue, tab, this_view):
    """If the Event is 404, but the issue is not, we can still show the issue page; we show a message for the event"""

    last_event = issue.event_set.order_by("timestamp").last()  # the template needs this for the tabs, we pick the last
    return render(request, "issues/event_404.html", {
        "tab": tab,
        "this_view": this_view,
        "project": issue.project,
        "issue": issue,
        "event": last_event,
        "is_event_page": False,  # this variable is used to denote "we have event-related info", which we don't
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@atomic_for_request_method
@issue_membership_required
def issue_event_breadcrumbs(request, issue, event_pk=None, digest_order=None, nav=None):
    if request.method == "POST":
        return _handle_post(request, issue)

    try:
        event = _get_event(issue, event_pk, digest_order, nav)
    except Event.DoesNotExist:
        return issue_event_404(request, issue, "breadcrumbs", "event_breadcrumbs")

    parsed_data = json.loads(event.data)

    return render(request, "issues/breadcrumbs.html", {
        "tab": "breadcrumbs",
        "this_view": "event_breadcrumbs",
        "project": issue.project,
        "issue": issue,
        "event": event,
        "is_event_page": True,
        "parsed_data": parsed_data,
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


def _date_with_milis_html(timestamp):
    return mark_safe(
        date(timestamp, "j M G:i:s") + "." +
        '<span class="text-xs">' + date(timestamp, "u")[:3] + '</span>')


@atomic_for_request_method
@issue_membership_required
def issue_event_details(request, issue, event_pk=None, digest_order=None, nav=None):
    if request.method == "POST":
        return _handle_post(request, issue)

    try:
        event = _get_event(issue, event_pk, digest_order, nav)
    except Event.DoesNotExist:
        return issue_event_404(request, issue, "event-details", "event_details")
    parsed_data = json.loads(event.data)

    key_info = [
        ("title", event.title()),
        ("event_id", event.event_id),
        ("bugsink_internal_id", event.id),
        ("issue_id", issue.id),
        ("timestamp", _date_with_milis_html(event.timestamp)),
        ("ingested at", _date_with_milis_html(event.ingested_at)),
        ("digested at", _date_with_milis_html(event.digested_at)),
        ("digest order", event.digest_order),
    ]
    if parsed_data.get("logger"):
        key_info.append(("logger", parsed_data["logger"]))

    deployment_info = \
        ([("release", parsed_data["release"])] if "release" in parsed_data else []) + \
        ([("environment", parsed_data["environment"])] if "environment" in parsed_data else []) + \
        ([("server_name", parsed_data["server_name"])] if "server_name" in parsed_data else [])

    contexts = enrich_contexts_with_ua(parsed_data)

    return render(request, "issues/event_details.html", {
        "tab": "event-details",
        "this_view": "event_details",
        "project": issue.project,
        "issue": issue,
        "event": event,
        "is_event_page": True,
        "parsed_data": parsed_data,
        "key_info": key_info,
        "deployment_info": deployment_info,
        "contexts": contexts,
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@atomic_for_request_method
@issue_membership_required
def issue_history(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    last_event = issue.event_set.order_by("timestamp").last()  # the template needs this for the tabs, we pick the last
    return render(request, "issues/history.html", {
        "tab": "history",
        "project": issue.project,
        "issue": issue,
        "event": last_event,
        "is_event_page": False,
        "parsed_data": json.loads(last_event.data),
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@atomic_for_request_method
@issue_membership_required
def issue_grouping(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    last_event = issue.event_set.order_by("timestamp").last()  # the template needs this for the tabs, we pick the last
    return render(request, "issues/grouping.html", {
        "tab": "grouping",
        "project": issue.project,
        "issue": issue,
        "event": last_event,
        "is_event_page": False,
        "parsed_data": json.loads(last_event.data),
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@atomic_for_request_method
@issue_membership_required
def issue_event_list(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    event_list = issue.event_set.order_by("digest_order")

    # re 250: in general "big is good" because it allows a lot "at a glance".
    paginator = Paginator(event_list, 250)

    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    last_event = issue.event_set.order_by("timestamp").last()  # the template needs this for the tabs, we pick the last
    return render(request, "issues/event_list.html", {
        "tab": "event-list",
        "project": issue.project,
        "issue": issue,
        "event": last_event,
        "event_list": event_list,
        "is_event_page": False,
        "parsed_data": json.loads(last_event.data),
        "mute_options": GLOBAL_MUTE_OPTIONS,
        "page_obj": page_obj,
    })


@atomic_for_request_method
@issue_membership_required
def history_comment_new(request, issue):

    if request.method == "POST":
        form = CommentForm(request.POST)
        assert form.is_valid()  # we have only a textfield with no validation properties; also: no html-side handling

        if form.cleaned_data["comment"] != "":
            # one special case: we simply ignore newly created comments without any contents as a (presumed) mistake. I
            # think that's amount of magic to have: it still allows one to erase comments (possibly for non-manual
            # kinds) but it saves you from what is obviously a mistake (without complaining with a red box or something)
            TurningPoint.objects.create(
                issue=issue, kind=TurningPointKind.MANUAL_ANNOTATION, user=request.user,
                comment=form.cleaned_data["comment"],
                timestamp=timezone.now())

        return redirect(issue_history, issue_pk=issue.pk)

    return HttpResponseNotAllowed(["POST"])


@atomic_for_request_method
@issue_membership_required
def history_comment_edit(request, issue, comment_pk):
    comment = get_object_or_404(TurningPoint, pk=comment_pk, issue_id=issue.pk)

    if comment.user_id != request.user.id:
        raise PermissionDenied("You can only edit your own comments")

    if request.method == "POST":
        form = CommentForm(request.POST, instance=comment)
        assert form.is_valid()
        form.save()
        return redirect(reverse(issue_history, kwargs={'issue_pk': issue.pk}) + f"#comment-{ comment_pk }")


@atomic_for_request_method
@issue_membership_required
def history_comment_delete(request, issue, comment_pk):
    comment = get_object_or_404(TurningPoint, pk=comment_pk, issue_id=issue.pk)

    if comment.user_id != request.user.id:
        raise PermissionDenied("You can only delete your own comments")

    if comment.kind != TurningPointKind.MANUAL_ANNOTATION:
        # I'm taking the 'allow almost nothing' path first
        raise PermissionDenied("You can only delete manual annotations")

    if request.method == "POST":
        comment.delete()
        return redirect(reverse(issue_history, kwargs={'issue_pk': issue.pk}))

    return HttpResponseNotAllowed(["POST"])
