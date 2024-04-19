from datetime import datetime, timezone
import json
import uuid
from dateutil.relativedelta import relativedelta
from functools import partial

from django.db import models, transaction
from django.db.models import F, Value
from django.template.defaultfilters import date as default_date_filter

from bugsink.volume_based_condition import VolumeBasedCondition
from alerts.tasks import send_unmute_alert
from compat.timestamp import parse_timestamp, format_timestamp

from .utils import (
    parse_lines, serialize_lines, filter_qs_for_fixed_at, exclude_qs_for_fixed_at,
    get_title_for_exception_type_and_value)


class IncongruentStateException(Exception):
    pass


class Issue(models.Model):
    """
    An Issue models a group of similar events. In particular: it models the result of both automatic (client-side and
    server-side) and manual ("merge") grouping.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    project = models.ForeignKey(
        "projects.Project", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    # 1-based for the same reasons as Event.ingest_order
    ingest_order = models.PositiveIntegerField(blank=False, null=False)

    # denormalized/cached fields:
    last_seen = models.DateTimeField(blank=False, null=False)  # based on event.server_side_timestamp
    first_seen = models.DateTimeField(blank=False, null=False)  # based on event.server_side_timestamp
    event_count = models.IntegerField(blank=False, null=False)
    calculated_type = models.CharField(max_length=255, blank=True, null=False, default="")
    calculated_value = models.CharField(max_length=255, blank=True, null=False, default="")
    transaction = models.CharField(max_length=200, blank=True, null=False, default="")
    last_frame_filename = models.CharField(max_length=255, blank=True, null=False, default="")
    last_frame_module = models.CharField(max_length=255, blank=True, null=False, default="")
    last_frame_function = models.CharField(max_length=255, blank=True, null=False, default="")

    # fields related to resolution:
    # what does this mean for the release-based use cases? it means what you filter on.
    # it also simply means: it was "marked as resolved" after the last regression (if any)
    is_resolved = models.BooleanField(default=False)
    is_resolved_by_next_release = models.BooleanField(default=False)

    fixed_at = models.TextField(blank=True, null=False, default='')  # line-separated list
    events_at = models.TextField(blank=True, null=False, default='')  # line-separated list

    # fields related to muting:
    is_muted = models.BooleanField(default=False)
    unmute_on_volume_based_conditions = models.TextField(blank=False, null=False, default="[]")  # json string
    unmute_after = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.ingest_order is None:
            # testing-only; in production this should never happen and instead have been done in the ingest view.
            max_current = self.ingest_order = Issue.objects.filter(project=self.project).aggregate(
                models.Max("ingest_order"))["ingest_order__max"]
            self.ingest_order = max_current + 1 if max_current is not None else 1
        super().save(*args, **kwargs)

    def friendly_id(self):
        return f"{ self.project.slug.upper() }-{ self.ingest_order }"

    def get_absolute_url(self):
        return f"/issues/issue/{ self.id }/event/last/"

    def title(self):
        return get_title_for_exception_type_and_value(self.calculated_type, self.calculated_value)

    def get_fixed_at(self):
        return parse_lines(self.fixed_at)

    def get_events_at(self):
        return parse_lines(self.events_at)

    def add_fixed_at(self, release_version):
        # release_version: str
        fixed_at = self.get_fixed_at()
        if release_version not in fixed_at:
            fixed_at.append(release_version)
            self.fixed_at = serialize_lines(fixed_at)

    def get_unmute_on_volume_based_conditions(self):
        return [
            VolumeBasedCondition.from_dict(vbc_s)
            for vbc_s in json.loads(self.unmute_on_volume_based_conditions)
        ]

    def occurs_in_last_release(self):
        return False  # TODO actually implement (and then: implement in a performant manner)

    def turningpoint_set_all(self):
        # like turningpoint_set.all() but with user in select_related
        return self.turningpoint_set.all().select_related("user")

    class Meta:
        unique_together = [
            ("project", "ingest_order"),
        ]
        indexes = [
            models.Index(fields=["first_seen"]),
            models.Index(fields=["last_seen"]),
        ]


class Grouping(models.Model):
    """A Grouping models an automatically calculated grouping key (from the event data, with a key role for the SDK-side
    fingerprint).
    """
    project = models.ForeignKey(
        "projects.Project", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    # NOTE: I don't want to have any principled maximum on the grouping key, nor do I want to prematurely optimize the
    # lookup. If lookups are slow, we _could_ examine whether manually hashing these values and matching on the hash
    # helps.
    grouping_key = models.TextField(blank=False, null=False)

    issue = models.ForeignKey("Issue", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    def __str__(self):
        return self.grouping_key


def add_periods_to_datetime(dt, nr_of_periods, period_name):
    dateutil_kwargs_map = {
        "year": "years",
        "month": "months",
        "week": "weeks",
        "day": "days",
        "hour": "hours",
        "minute": "minutes",
    }
    return dt + relativedelta(**{dateutil_kwargs_map[period_name]: nr_of_periods})


def format_unmute_reason(unmute_metadata):
    if "mute_until" in unmute_metadata:
        d = unmute_metadata["mute_until"]
        plural_s = "" if d["nr_of_periods"] == 1 else "s"
        return f"More than { d['volume'] } events per { d['nr_of_periods'] } { d['period'] }{ plural_s } occurred, "\
               f"unmuting the issue."

    d = unmute_metadata["mute_for"]
    formatted_date = default_date_filter(d['unmute_after'], 'j M G:i')
    return f"An event was observed after the mute-deadline of { formatted_date } and the issue was unmuted."


class IssueStateManager(object):
    """basically: a namespace; with static methods that combine field-setting in a single place"""

    # NOTE I'm not so sure about the exact responsibilities of this thingie yet. In particular:
    # * save() is now done outside;  (I'm not sure it's "right", but it's shorter because we do this for each action)
    # * alerts are sent from inside.

    @staticmethod
    def resolve(issue):
        issue.is_resolved = True
        issue.add_fixed_at("")  # i.e. fixed in the no-release-info-available release

        # an issue cannot be both resolved and muted; muted means "the problem persists but don't tell me about it
        # (or maybe unless some specific condition happens)" and resolved means "the problem is gone". Hence, resolving
        # an issue means unmuting it. Note that resolve-after-mute is implemented as an override but mute-after-resolve
        # is implemented as an Exception; this is because from a usage perspective saying "I don't care about this" but
        # then solving it anyway is a realistic scenario and the reverse is not.
        IssueStateManager.unmute(issue)

    @staticmethod
    def resolve_by_latest(issue):
        # NOTE: currently unused; we may soon reintroduce it though so I left it in.
        issue.is_resolved = True
        issue.add_fixed_at(issue.project.get_latest_release().version)
        IssueStateManager.unmute(issue)  # as in IssueStateManager.resolve()

    @staticmethod
    def resolve_by_release(issue, release_version):
        # release_version: str
        issue.is_resolved = True
        issue.add_fixed_at(release_version)
        IssueStateManager.unmute(issue)  # as in IssueStateManager.resolve()

    @staticmethod
    def resolve_by_next(issue):
        issue.is_resolved = True
        issue.is_resolved_by_next_release = True
        IssueStateManager.unmute(issue)  # as in IssueStateManager.resolve()

    @staticmethod
    def reopen(issue):
        issue.is_resolved = False
        issue.is_resolved_by_next_release = False  # ?? echt?
        # TODO and what about fixed_at ?

        # as in IssueStateManager.resolve(), but not because a reopened issue cannot be muted (we could mute it soon
        # after reopening) but because when reopening an issue you're doing this from a resolved state; calling unmute()
        # here is done as a consistency-enforcement after the fact.
        IssueStateManager.unmute(issue)

    @staticmethod
    def mute(issue, unmute_on_volume_based_conditions="[]", unmute_after=None):
        from bugsink.registry import get_pc_registry  # avoid circular import
        if issue.is_resolved:
            raise IncongruentStateException("Cannot mute a resolved issue")

        now = datetime.now(timezone.utc)  # NOTE: clock-reading going on here... should it be passed-in?

        issue.is_muted = True
        issue.unmute_on_volume_based_conditions = unmute_on_volume_based_conditions

        transaction.on_commit(partial(IssueStateManager.set_unmute_handlers,
                                      get_pc_registry().by_issue, issue, now))

        if unmute_after is not None:
            issue.unmute_after = unmute_after

    @staticmethod
    def unmute(issue, triggering_event=None, unmute_metadata=None):
        from bugsink.registry import get_pc_registry, UNMUTE_PURPOSE  # avoid circular import

        if issue.is_muted:
            # we check on is_muted explicitly: it may be so that multiple unmute conditions happens simultaneously (and
            # not just in "funny configurations"). i.e. a single event could push you past more than 3 events per day or
            # 100 events per year. We don't want 2 "unmuted" alerts being sent in that case.

            issue.is_muted = False
            issue.unmute_on_volume_based_conditions = "[]"
            issue.unmute_after = None

            # NOTE I'm not sure how I feel about reaching out to the global registry here; consider pass-along.
            # Keep the pc_registry and the value of issue.unmute_on_volume_based_conditions in-sync:
            get_pc_registry().by_issue[issue.id].remove_event_listener(UNMUTE_PURPOSE)

            if triggering_event is not None:
                # (note: we can expect project to be set, because it will be None only when projects are deleted, in
                # which case no more unmuting happens)
                if issue.project.alert_on_unmute:
                    transaction.on_commit(partial(
                        send_unmute_alert.delay,
                        str(issue.id), format_unmute_reason(unmute_metadata)))

                # this is in a funny place but it's still simpler than introducing an Encoder
                if unmute_metadata is not None and "mute_for" in unmute_metadata:
                    unmute_metadata["mute_for"]["unmute_after"] = \
                        format_timestamp(unmute_metadata["mute_for"]["unmute_after"])

                # by sticking close to the point where we call send_unmute_alert.delay, we reuse any thinking about
                # avoinding double calls in edge-cases. a "coincidental advantage" of this approach is that the current
                # path is never reached via UI-based paths (because those are by definition not event-triggered); thus
                # the 2 ways of creating TurningPoints do not collide.
                TurningPoint.objects.create(
                    issue=issue, triggering_event=triggering_event, timestamp=triggering_event.server_side_timestamp,
                    kind=TurningPointKind.UNMUTED, metadata=json.dumps(unmute_metadata))

    @staticmethod
    def set_unmute_handlers(by_issue, issue, now):
        from bugsink.registry import UNMUTE_PURPOSE  # avoid circular import
        issue_pc = by_issue[issue.id]

        unmute_vbcs = [
            VolumeBasedCondition.from_dict(vbc_s)
            for vbc_s in json.loads(issue.unmute_on_volume_based_conditions)
        ]

        # remove_event_listener(UNMUTE_PURPOSE) is (given the current constraints in our UI) not needed here, because we
        # can only reach this point for currently unmuted (and hence without listeners) issues. Somewhat related note
        # about this for-loop: with our current UI this loop always contains 0 or 1 elements, adding another unmute
        # condition for an already-muted issue is simply not possible. If the UI ever changes, we need to double-check
        # whether this still holds up.
        for vbc in unmute_vbcs:
            initial_state = issue_pc.add_event_listener(
                period_name=vbc.period,
                nr_of_periods=vbc.nr_of_periods,
                gte_threshold=vbc.volume,
                when_becomes_true=create_unmute_issue_handler(issue.id, vbc.to_dict()),
                tup=now.timetuple(),
                purpose=UNMUTE_PURPOSE,
            )
            if initial_state:
                # What do you really mean when passing an unmute-condition that is immediately true? Probably: not what
                # you asked for (you asked for muting, but provided a condition that would immediately unmute).
                #
                # We guard for this also because in our implementation, having passed the "become true" point means that
                # in fact the condition will only become true _after_ it has become false once. (i.e. the opposite of
                # what you'd expect).
                #
                # Whether to raise an Exception (rather than e.g. validate, or warn, or whatever) is an open question.
                # For now we do it to avoid surprises.
                #
                # One alternative implementation would be: immediately unmute (but that's surprising too!)
                # (All of the above applies equally well to at-unmute as it does for load_from_scratch (at which point
                # we also just expect unmute conditions to only be set when they can still be triggered)
                raise Exception("The unmute condition is already true")


class IssueQuerysetStateManager(object):
    """
    This is exaclty the same as IssueStateManager, but it works on querysets instead of single objects.
    The reason we do this as a copy/pasta (and not by just passing a queryset with a single element) is twofold:

    * the qs-approach is harder to comprehend; understanding can be aided by referring back to the simple approach
    * performance: the qs-approach may take a few queries to deal with a whole set; but when working on a single object
        a single .save() is enough.
    """

    # NOTE I'm not so sure about the exact responsibilities of this thingie yet. In particular:
    # * alerts are sent from inside.

    # NOTE: the methods in this class work on issue_qs; this allows us to do database operations over multiple objects
    # as a single query (but for our hand-made in-python operations, we obviously still just loop over the elements)

    def _resolve_at(issue_qs, release_version):
        filter_qs_for_fixed_at(issue_qs, release_version).update(
            is_resolved=True,
        )
        exclude_qs_for_fixed_at(issue_qs, "").update(
            is_resolved=True,
            fixed_at=F("fixed_at") + Value(release_version + "\n"),
        )

        # release_version: str
        issue_qs.update(
            fixed_at=F("fixed_at") + Value(release_version + "\n"),
        )

    @staticmethod
    def resolve(issue_qs):
        IssueQuerysetStateManager._resolve_at(issue_qs, "")  # i.e. fixed in the no-release-info-available release

        # an issue cannot be both resolved and muted; muted means "the problem persists but don't tell me about it
        # (or maybe unless some specific condition happens)" and resolved means "the problem is gone". Hence, resolving
        # an issue means unmuting it. Note that resolve-after-mute is implemented as an override but mute-after-resolve
        # is implemented as an Exception; this is because from a usage perspective saying "I don't care about this" but
        # then solving it anyway is a realistic scenario and the reverse is not.
        IssueQuerysetStateManager.unmute(issue_qs)

    @staticmethod
    def resolve_by_latest(issue_qs):
        # NOTE: currently unused; we may soon reintroduce it though so I left it in.
        # However, since it's unused, I'm not going to fix the line below, which doesn't work because issue.project is
        # not available; (we might consider adding the restriction that project is always the same; or pass it in
        # explicitly)

        raise NotImplementedError("resolve_by_latest is not implemented - see comments above")
        # the solution is along these lines, but with the project passed in:
        # IssueQuerysetStateManager._resolve_at(issue_qs, issue.project.get_latest_release().version)
        # IssueQuerysetStateManager.unmute(issue_qs)  # as in IssueQuerysetStateManager.resolve()

    @staticmethod
    def resolve_by_release(issue_qs, release_version):
        # release_version: str
        IssueQuerysetStateManager._resolve_at(issue_qs, release_version)
        IssueQuerysetStateManager.unmute(issue_qs)  # as in IssueQuerysetStateManager.resolve()

    @staticmethod
    def resolve_by_next(issue_qs):
        issue_qs.update(
            is_resolved=True,
            is_resolved_by_next_release=True,
        )

        IssueQuerysetStateManager.unmute(issue_qs)  # as in IssueQuerysetStateManager.resolve()

    @staticmethod
    def reopen(issue_qs):
        # we don't need reopen() over a queryset (yet); reason being that we don't allow reopening of issues from the UI
        # and hence not in bulk.
        raise NotImplementedError("reopen is not implemented - see comments above")

    @staticmethod
    def mute(issue_qs, unmute_on_volume_based_conditions="[]", unmute_after=None):
        from bugsink.registry import get_pc_registry  # avoid circular import
        if issue_qs.filter(is_resolved=True).exists():
            # we might remove this check for performance reasons later (it's more expensive here than in the non-bulk
            # case because we have to do a query to check for it). For now we leave it in to avoid surprises while we're
            # still heavily in development.
            raise IncongruentStateException("Cannot mute a resolved issue")

        now = datetime.now(timezone.utc)  # NOTE: clock-reading going on here... should it be passed-in?

        issue_qs.update(
            is_muted=True,
            unmute_on_volume_based_conditions=unmute_on_volume_based_conditions,
        )

        transaction.on_commit(partial(
            IssueQuerysetStateManager.set_unmute_handlers,
            get_pc_registry().by_issue, [i for i in issue_qs], now))

        if unmute_after is not None:
            issue_qs.update(unmute_after=unmute_after)

    @staticmethod
    def unmute(issue_qs, triggering_event=None):
        issue_qs.update(
            is_muted=False,
            unmute_on_volume_based_conditions="[]",
            unmute_after=None,
        )

        assert triggering_event is None, "this method can only be called from the UI, i.e. user-not-event-triggered"
        # for the rest of this method there's no fancy queryset based stuff (we don't actually do updates on the DB)
        # we resist the temptation to add filter(is_muted=True) in the below because that would actually add a query
        # (for this remark to be true triggering_event must be None, which is asserted for in the above)
        for issue in issue_qs:
            IssueStateManager.unmute(issue, triggering_event)

    @staticmethod
    def set_unmute_handlers(by_issue, issue_list, now):
        # in this method there's no fancy queryset based stuff (we don't actually do updates on the DB)
        # the use of 'issue_list' as opposed to 'issue_qs' is a (non-enforced) indication that for correct usage (in
        # on_commit) as QS should be evaluated inside the commit and the resulting list should be dealt with afterwards.

        for issue in issue_list:
            IssueStateManager.set_unmute_handlers(by_issue, issue, now)


def create_unmute_issue_handler(issue_id, vbc_dict):
    # as an alternative solution to storing vbc_dict in the closure I considered passing the (period, gte_threshold)
    # info from the PeriodCounter (in the when_becomes_true call), but the current solution works just as well and
    # requires less rework.

    def unmute(counted_entity):
        issue = Issue.objects.get(id=issue_id)
        IssueStateManager.unmute(issue, triggering_event=counted_entity, unmute_metadata={"mute_until": vbc_dict})
        issue.save()

    return unmute


class TurningPointKind(models.IntegerChoices):
    # The language of the kinds reflects a historic view of the system, e.g. "first seen" as opposed to "new issue"; an
    # alternative take (which is more consistent with the language used elsewhere" is a more "active" language.
    FIRST_SEEN = 1, "First seen"
    RESOLVED = 2, "Resolved"
    MUTED = 3, "Muted"
    REGRESSED = 4, "Marked as regressed"
    UNMUTED = 5, "Unmuted"

    NEXT_MATERIALIZED = 10, "Release info added"

    # ASSGINED = 10, "Assigned to user"   # perhaps later
    MANUAL_ANNOTATION = 100, "Manual annotation"


class TurningPoint(models.Model):
    """A TurningPoint models a point in time in the history of an issue."""
    # basically: an Event, but that name was already taken in our system :-) alternative names I considered:
    # "milestone", "state_change", "transition", "annotation", "episode"

    issue = models.ForeignKey("Issue", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    triggering_event = models.ForeignKey("events.Event", blank=True, null=True, on_delete=models.SET_NULL)
    user = models.ForeignKey("auth.User", blank=True, null=True, on_delete=models.SET_NULL)  # null: the system-user
    timestamp = models.DateTimeField(blank=False, null=False)  # this info is also in the event, but event is nullable
    kind = models.IntegerField(blank=False, null=False, choices=TurningPointKind.choices)
    metadata = models.TextField(blank=False, null=False, default="{}")  # json string
    comment = models.TextField(blank=True, null=False, default="")

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"]),
        ]

    def parsed_metadata(self):
        if not hasattr(self, "_parsed_metadata"):
            self._parsed_metadata = json.loads(self.metadata)
            # rather than doing some magic using an encoder/decoder we just convert the single value that we know to be
            # time
            if "mute_for" in self._parsed_metadata and "unmute_after" in self._parsed_metadata["mute_for"]:
                self._parsed_metadata["mute_for"]["unmute_after"] = \
                    parse_timestamp(self._parsed_metadata["mute_for"]["unmute_after"])
        return self._parsed_metadata
