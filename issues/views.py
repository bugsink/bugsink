from collections import namedtuple
import json
import sentry_sdk

from django.db.models import Q
from django.utils import timezone
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseRedirect, HttpResponseNotAllowed
from django.utils.safestring import mark_safe
from django.template.defaultfilters import date
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.core.paginator import Paginator, Page
from django.db.utils import OperationalError

from sentry.utils.safe import get_path

from bugsink.decorators import project_membership_required, issue_membership_required, atomic_for_request_method
from bugsink.transaction import durable_atomic
from bugsink.period_utils import add_periods_to_datetime
from bugsink.timed_sqlite_backend.base import different_runtime_limit

from events.models import Event
from events.ua_stuff import get_contexts_enriched_with_ua

from compat.timestamp import format_timestamp
from projects.models import ProjectMembership
from tags.search import search_issues, search_events, search_events_optimized

from .models import Issue, IssueQuerysetStateManager, IssueStateManager, TurningPoint, TurningPointKind
from .forms import CommentForm
from .utils import get_values, get_main_exception
from events.utils import annotate_with_meta


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


class EagerPaginator(Paginator):
    # Eager meaning non-lazy; this is a paginator that doesn't postpone the query (implicit in object_list) until the
    # last moment (i.e. when the page is actually rendered). Prompted by the following unhappy combination of facts:
    # * failure in evaluation in the object_list (in my case interrupt, but since this is DB-related: could be anything)
    # * usage of sentry_sdk (when dogfooding)
    # * sentry_sdk's serializer sees a Sequence (Page is a subclass of that) and proceeds accordingly ("fancily")
    # * evaluating the qs and putting it in a list (caching) is in Page.__getitem__ only
    # together, this means that sentry_sdk's serializer will again try to evaulate the QS, right after (and because),
    # this failed, in an attempt to serialize local vars. When that happens: again. Etc.
    #
    # I'm blaming Django, btw: if you implement Sequence, don't do database stuff to get elements.
    #
    # On the now-removed lazyness: when you generate a page, you're going to display it, so just do that right away.

    def _get_page(self, *args, **kwargs):
        object_list = args[0]
        object_list = list(object_list)
        return Page(object_list, *(args[1:]), **kwargs)


class KnownCountPaginator(EagerPaginator):
    """optimization: we know the total count of the queryset, so we can avoid a count() query"""

    def __init__(self, *args, **kwargs):
        self._count = kwargs.pop("count")
        super().__init__(*args, **kwargs)

    @property
    def count(self):
        return self._count


def _request_repr(parsed_data):
    if "request" not in parsed_data:
        return ""

    return parsed_data["request"].get("method", "") + " " + parsed_data["request"].get("url", "")


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

    if request.GET.get("q"):
        issue_list = search_issues(project, issue_list, request.GET["q"])

    paginator = EagerPaginator(issue_list, 250)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

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
        "page_obj": page_obj,
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


def _get_event(qs, issue, event_pk, digest_order, nav, bounds):
    """
    Returns the event using the "url lookup".
    The passed qs is "something you can use to deduce digest_order (for next/prev)."
    When a direct (non-nav) method is used, we do _not_ check against existence in qs; this is more performant, and it's
    not clear that being pedantic in this case is actually more valuable from a UX perspective.
    """

    if nav is not None:
        if nav not in ["first", "last", "prev", "next"]:
            raise Http404("Cannot look up with '%s'" % nav)

        if nav == "first":
            # basically, the below. But because first/last are calculated anyway for "_has_next_prev", we pass these
            # digest_order = qs.order_by("digest_order").values_list("digest_order", flat=True).first()
            digest_order = bounds[0]
        elif nav == "last":
            # digest_order = qs.order_by("digest_order").values_list("digest_order", flat=True).last()
            digest_order = bounds[1]
        elif nav in ["prev", "next"]:
            if digest_order is None:
                raise Http404("Cannot look up with '%s' without digest_order" % nav)

            if nav == "prev":
                digest_order = qs.filter(digest_order__lt=digest_order).values_list("digest_order", flat=True)\
                    .order_by("-digest_order").first()
            elif nav == "next":
                digest_order = qs.filter(digest_order__gt=digest_order).values_list("digest_order", flat=True)\
                    .order_by("digest_order").first()

        if digest_order is None:
            raise Event.DoesNotExist
        return Event.objects.get(issue=issue, digest_order=digest_order)

    elif event_pk is not None:
        # we match on both internal and external id, trying internal first
        try:
            return Event.objects.get(pk=event_pk)
        except Event.DoesNotExist:
            return Event.objects.get(event_id=event_pk)

    elif digest_order is not None:
        return Event.objects.get(digest_order=digest_order)
    else:
        raise Http404("Either event_pk, nav, or digest_order must be provided")


def _event_count(request, issue, event_x_qs):
    # We want to be able to show the number of matching events for some query in the UI, but counting is potentially
    # expensive, because it's a full scan over all matching events. We just show "many" if this takes too long.
    # different_runtime_limit is sqlite-only, it doesn't affect other backends.

    with different_runtime_limit(0.1):
        try:
            return event_x_qs.count() if request.GET.get("q") else issue.stored_event_count
        except OperationalError as e:
            if e.args[0] != "interrupted":
                raise
            return "many"


@atomic_for_request_method
@issue_membership_required
def issue_event_stacktrace(request, issue, event_pk=None, digest_order=None, nav=None):
    if request.method == "POST":
        return _handle_post(request, issue)

    event_x_qs = search_events_optimized(issue.project, issue, request.GET.get("q", ""))
    first_do, last_do = _first_last(event_x_qs)

    try:
        event = _get_event(event_x_qs, issue, event_pk, digest_order, nav, (first_do, last_do))
    except Event.DoesNotExist:
        return issue_event_404(request, issue, event_x_qs, "stacktrace", "event_stacktrace")

    parsed_data = event.get_parsed_data()

    exceptions = get_values(parsed_data["exception"]) if "exception" in parsed_data else None

    try:
        # get_values for consistency (whether it's needed: unclear, since _meta is not actually in the specs)
        meta_values = get_values(parsed_data.get("_meta", {}).get("exception", {"values": {}}))
        annotate_with_meta(exceptions, meta_values)
    except Exception as e:
        # broad Exception handling: "_meta" is completely undocumented, and though we have some example of event-data
        # with "_meta" in it, we're not quite sure what the full structure could be in the wild. Because the
        # 'incomplete' annotations are not absolutely necessary (Sentry itself went without it for years) we silently
        # swallow the error in that case.
        sentry_sdk.capture_exception(e)

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
        "request_repr": _request_repr(parsed_data),
        "exceptions": exceptions,
        "stack_of_plates": stack_of_plates,
        "mute_options": GLOBAL_MUTE_OPTIONS,
        "q": request.GET.get("q", ""),
        "event_qs_count": _event_count(request, issue, event_x_qs),
        "has_prev": event.digest_order > first_do,
        "has_next": event.digest_order < last_do,
    })


def issue_event_404(request, issue, event_x_qs, tab, this_view):
    """If the Event is 404, but the issue is not, we can still show the issue page; we show a message for the event"""

    return render(request, "issues/event_404.html", {
        "tab": tab,
        "this_view": this_view,
        "project": issue.project,
        "issue": issue,
        "is_event_page": False,  # this variable is used to denote "we have event-related info", which we don't
        "mute_options": GLOBAL_MUTE_OPTIONS,
        "q": request.GET.get("q", ""),
        "event_qs_count": _event_count(request, issue, event_x_qs),
    })


@atomic_for_request_method
@issue_membership_required
def issue_event_breadcrumbs(request, issue, event_pk=None, digest_order=None, nav=None):
    if request.method == "POST":
        return _handle_post(request, issue)

    event_x_qs = search_events_optimized(issue.project, issue, request.GET.get("q", ""))
    first_do, last_do = _first_last(event_x_qs)

    try:
        event = _get_event(event_x_qs, issue, event_pk, digest_order, nav, (first_do, last_do))
    except Event.DoesNotExist:
        return issue_event_404(request, issue, event_x_qs, "breadcrumbs", "event_breadcrumbs")

    parsed_data = event.get_parsed_data()

    return render(request, "issues/breadcrumbs.html", {
        "tab": "breadcrumbs",
        "this_view": "event_breadcrumbs",
        "project": issue.project,
        "issue": issue,
        "event": event,
        "is_event_page": True,
        "request_repr": _request_repr(parsed_data),
        "breadcrumbs": get_values(parsed_data.get("breadcrumbs")),
        "mute_options": GLOBAL_MUTE_OPTIONS,
        "q": request.GET.get("q", ""),
        "event_qs_count": _event_count(request, issue, event_x_qs),
        "has_prev": event.digest_order > first_do,
        "has_next": event.digest_order < last_do,
    })


def _date_with_milis_html(timestamp):
    return mark_safe(
        date(timestamp, "j M G:i:s") + "." +
        '<span class="text-xs">' + date(timestamp, "u")[:3] + '</span>')


def _first_last(qs_with_digest_order):
    # this was once implemented with Min/Max, but just doing 2 queries is (on sqlite at least) much faster.
    first = qs_with_digest_order.order_by("digest_order").values_list("digest_order", flat=True).first()
    last = qs_with_digest_order.order_by("-digest_order").values_list("digest_order", flat=True).first()
    return first, last


@atomic_for_request_method
@issue_membership_required
def issue_event_details(request, issue, event_pk=None, digest_order=None, nav=None):
    if request.method == "POST":
        return _handle_post(request, issue)

    event_x_qs = search_events_optimized(issue.project, issue, request.GET.get("q", ""))
    first_do, last_do = _first_last(event_x_qs)

    try:
        event = _get_event(event_x_qs, issue, event_pk, digest_order, nav, (first_do, last_do))
    except Event.DoesNotExist:
        return issue_event_404(request, issue, event_x_qs, "event-details", "event_details")
    parsed_data = event.get_parsed_data()

    key_info = [
        ("title", event.title()),
        ("transaction", issue.transaction),
        # transaction_info.source avoid information overload; sentry doesn't bother showing this in the UI either
        ("event_id", event.event_id),
        ("bugsink_internal_id", event.id),
    ]

    if get_path(get_main_exception(parsed_data), "mechanism", "handled") is not None:
        key_info += [
            # grepping on [private-]samples (admittedly: not a very rich set)  has shown: when there's multiple values
            # for mechanism, they're always identical. We just pick the 'main' (best guess) if this ever turns out to be
            # false.  sentry repeats this info throughout the chains in the trace, btw, but I don't want to pollute my
            # UI so much.
            ("handled", get_path(get_main_exception(parsed_data), "mechanism", "handled")),
        ]

    key_info += [
        ("mechanism", get_path(get_main_exception(parsed_data), "mechanism", "type")),

        ("issue_id", issue.id),
        ("timestamp", _date_with_milis_html(event.timestamp)),
        ("ingested at", _date_with_milis_html(event.ingested_at)),
        ("digested at", _date_with_milis_html(event.digested_at)),
        ("digest order", event.digest_order),
    ]

    logentry_info = []
    if parsed_data.get("logger") or parsed_data.get("logentry") or parsed_data.get("message"):
        if "level" in parsed_data:
            # Sentry gives "level" a front row seat in the UI; but we don't: in an Error Tracker, the default is just
            # "error" (and we don't want to pollute the UI with this info). Sentry's documentation is also very sparse
            # on what this actually could be used for, other than that it's "similar" to the log level. I'm just going
            # to interpret that as "it _is_ the log level" and show it in the logentry_info (only).
            # Best source is: https://docs.sentry.dev/platforms/python/usage/set-level/
            logentry_info.append(("level", parsed_data["level"]))

        if parsed_data.get("logger"):
            logentry_info.append(("logger", parsed_data["logger"]))

        # "message" is a fallback location for the logentry message. It's not in the specs, but it probably was in the
        # past. see https://github.com/bugsink/bugsink/issues/43
        logentry_key = "logentry" if "logentry" in parsed_data else "message"

        if isinstance(parsed_data.get(logentry_key), dict):
            if parsed_data.get(logentry_key, {}).get("message"):
                logentry_info.append(("message", parsed_data[logentry_key]["message"]))

            params = parsed_data.get(logentry_key, {}).get("params", {})
            if isinstance(params, list):
                for param_i, param_v in enumerate(params):
                    logentry_info.append(("#%s" % param_i, param_v))
            elif isinstance(params, dict):
                for param_k, param_v in params.items():
                    logentry_info.append((param_k, param_v))

        elif isinstance(parsed_data.get(logentry_key), str):
            logentry_info.append(("message", parsed_data[logentry_key]))

    key_info += [
        ("grouping key", event.grouping.grouping_key),
    ]

    deployment_info = \
        ([("release", parsed_data["release"])] if "release" in parsed_data else []) + \
        ([("environment", parsed_data["environment"])] if "environment" in parsed_data else []) + \
        ([("server_name", parsed_data["server_name"])] if "server_name" in parsed_data else [])

    contexts = get_contexts_enriched_with_ua(parsed_data)

    return render(request, "issues/event_details.html", {
        "tab": "event-details",
        "this_view": "event_details",
        "project": issue.project,
        "issue": issue,
        "event": event,
        "is_event_page": True,
        "parsed_data": parsed_data,
        "request_repr": _request_repr(parsed_data),
        "key_info": key_info,
        "logentry_info": logentry_info,
        "deployment_info": deployment_info,
        "contexts": contexts,
        "mute_options": GLOBAL_MUTE_OPTIONS,
        "q": request.GET.get("q", ""),
        "event_qs_count": _event_count(request, issue, event_x_qs),
        "has_prev": event.digest_order > first_do,
        "has_next": event.digest_order < last_do,
    })


@atomic_for_request_method
@issue_membership_required
def issue_history(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    event_qs = search_events(issue.project, issue, request.GET.get("q", ""))
    last_event = event_qs.order_by("digest_order").last()
    return render(request, "issues/history.html", {
        "tab": "history",
        "project": issue.project,
        "issue": issue,
        "is_event_page": False,
        "request_repr": _request_repr(last_event.get_parsed_data()) if last_event is not None else "",
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@atomic_for_request_method
@issue_membership_required
def issue_tags(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    event_qs = search_events(issue.project, issue, request.GET.get("q", ""))
    last_event = event_qs.order_by("digest_order").last()
    return render(request, "issues/tags.html", {
        "tab": "tags",
        "project": issue.project,
        "issue": issue,
        "is_event_page": False,
        "request_repr": _request_repr(last_event.get_parsed_data()) if last_event is not None else "",
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@atomic_for_request_method
@issue_membership_required
def issue_grouping(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    event_qs = search_events(issue.project, issue, request.GET.get("q", ""))
    last_event = event_qs.order_by("digest_order").last()
    return render(request, "issues/grouping.html", {
        "tab": "grouping",
        "project": issue.project,
        "issue": issue,
        "is_event_page": False,
        "request_repr": _request_repr(last_event.get_parsed_data()) if last_event is not None else "",
        "mute_options": GLOBAL_MUTE_OPTIONS,
    })


@atomic_for_request_method
@issue_membership_required
def issue_event_list(request, issue):
    if request.method == "POST":
        return _handle_post(request, issue)

    # because we we need _actual events_ for display, and we don't have the regular has_prev/has_next (paginator
    # instead), we don't try to optimize using search_events_optimized in this view (except for counting)
    if "q" in request.GET:
        event_list = search_events(issue.project, issue, request.GET["q"]).order_by("digest_order")
        event_x_qs = search_events_optimized(issue.project, issue, request.GET.get("q", ""))
        # we don't do the `_event_count` optimization here, because we need the correct number for pagination
        paginator = KnownCountPaginator(event_list, 250, count=event_x_qs.count())
    else:
        event_list = issue.event_set.order_by("digest_order")
        # re 250: in general "big is good" because it allows a lot "at a glance".
        paginator = KnownCountPaginator(event_list, 250, count=issue.stored_event_count)

    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    last_event = event_list.last()

    return render(request, "issues/event_list.html", {
        "tab": "event-list",
        "project": issue.project,
        "issue": issue,
        "event_list": event_list,
        "is_event_page": False,
        "request_repr": _request_repr(last_event.get_parsed_data()) if last_event is not None else "",
        "mute_options": GLOBAL_MUTE_OPTIONS,
        "q": request.GET.get("q", ""),
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
