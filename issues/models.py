import json
import uuid
from functools import partial

from django.db import models, transaction
from django.db.models import F, Value
from django.db.models.functions import Concat
from django.template.defaultfilters import date as default_date_filter
from django.conf import settings
from django.utils.functional import cached_property

from bugsink.volume_based_condition import VolumeBasedCondition
from alerts.tasks import send_unmute_alert
from compat.timestamp import parse_timestamp, format_timestamp
from tags.models import IssueTag, TagValue

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

    # 1-based for the same reasons as Event.digest_order
    digest_order = models.PositiveIntegerField(blank=False, null=False)

    # denormalized/cached fields:
    last_seen = models.DateTimeField(blank=False, null=False)  # based on event.ingested_at
    first_seen = models.DateTimeField(blank=False, null=False)  # based on event.ingested_at
    digested_event_count = models.IntegerField(blank=False, null=False)
    stored_event_count = models.IntegerField(blank=False, null=False, default=0, editable=False)
    calculated_type = models.CharField(max_length=128, blank=True, null=False, default="")
    calculated_value = models.TextField(max_length=1024, blank=True, null=False, default="")
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
    next_unmute_check = models.PositiveIntegerField(null=False, default=0)

    def save(self, *args, **kwargs):
        if self.digest_order is None:
            # testing-only; in production this should never happen and instead have been done in the ingest view.
            max_current = self.digest_order = Issue.objects.filter(project=self.project).aggregate(
                models.Max("digest_order"))["digest_order__max"]
            self.digest_order = max_current + 1 if max_current is not None else 1
        super().save(*args, **kwargs)

    def friendly_id(self):
        return f"{ self.project.slug.upper() }-{ self.digest_order }"

    def get_absolute_url(self):
        return f"/issues/issue/{ self.id }/event/last/"

    def title(self):
        return get_title_for_exception_type_and_value(self.calculated_type, self.calculated_value)

    def get_fixed_at(self):
        return parse_lines(self.fixed_at)

    def get_events_at(self):
        return parse_lines(self.events_at)

    def get_events_at_2(self):
        # _2: a great Python tradition; in this case: the same as get_events_at(), but ignoring the 'no release' release
        return [e for e in self.get_events_at() if e != ""]

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
        # we can depend on latest_release to exist, because we always create at least one release, even for 'no release'
        latest_release = self.project.get_latest_release()
        return latest_release.version in self.events_at

    def turningpoint_set_all(self):
        # like turningpoint_set.all() but with user in select_related
        return self.turningpoint_set.all().select_related("user")

    @cached_property
    def tags_summary(self):
        return self._get_issue_tags(4, "...")

    @cached_property
    def tags_all(self):
        # NOTE: Having 25 as a cut-off means there's no way to see all tags when there's more than 25; the way to do
        # that would be to have a per-key (per issue) page (paginated); for now I don't see the value in that TBH,
        # because you're well past "this is something I can eyeball-analyse" territory at that point.
        return self._get_issue_tags(25, "Other...")

    def _get_issue_tags(self, other_cutoff, other_label):
        result = []

        ds = self.tags \
            .filter(key__mostly_unique=False)\
            .values("key")\
            .annotate(count_sum=models.Sum("count"))\
            .distinct()\
            .order_by("key__key")

        for d in ds:
            issue_tags = [
                issue_tag
                for issue_tag in
                (IssueTag.objects
                 .filter(issue=self, key=d['key'])  # note: project is implied through issue
                 .order_by("-count")
                 .select_related("value", "key")[:other_cutoff + 1]  # +1 to see if we need to add "Other"
                 )
            ]

            total_seen = d["count_sum"]

            seen_till_now = 0
            if len(issue_tags) > other_cutoff:
                issue_tags = issue_tags[:other_cutoff - 1]  # cut off one more to make room for "Other"

            for i, issue_tag in enumerate(issue_tags):
                issue_tag.pct = int(issue_tag.count / total_seen * 100)
                seen_till_now += issue_tag.count

            if seen_till_now < total_seen:
                issue_tags.append({
                    "value": TagValue(value=other_label),
                    "count": total_seen - seen_till_now,
                    "pct": int((total_seen - seen_till_now) / total_seen * 100),
                })

            result.append(issue_tags)

        return result

    class Meta:
        unique_together = [
            ("project", "digest_order"),
        ]
        indexes = [
            models.Index(fields=["first_seen"]),
            models.Index(fields=["last_seen"]),

            # 3 indexes for the list view (state_filter)
            models.Index(fields=["is_resolved", "is_muted", "last_seen"]),  # filter on resolved/muted
            models.Index(fields=["is_muted", "last_seen"]),  # filter on muted
            models.Index(fields=["is_resolved", "last_seen"]),  # filter on resolved
        ]


class Grouping(models.Model):
    """
    Grouping models the automatic part of Events should be grouped into Issues. In particular: an automatically
    calculated grouping key (from the event data, with a key role for the SDK-side fingerprint).

    They are separated out into a separate model to allow for manually merging (after the fact) multiple such groupings
    into a single issue. (such manual merging is not yet implemented, but the data-model is already prepared for it)
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
        # this is called "reopen", but since there's no UI for it, it's more like "deal with a regression" (i.e. that's
        # the only way this gets called).
        issue.is_resolved = False

        # we don't touch is_resolved_by_next_release (i.e. set to False) here. Why? The simple/principled answer is that
        # observations that Bugsink can make can by definition not be about the future. If the user tells us "this
        # is fixed in some not-yet-released version" there's just no information ever in Bugsink to refute that".
        # (BTW this point in the code cannot be reached when issue.is_resolved_by_next_release is True anyway)

        # we also don't touch `fixed_at`. The meaning of that field is "reports came in about fixes at these points in
        # time", not "it actually _was_ fixed at all of those points" and the finer differences between those 2
        # statements is precisely what we have quite some "is_regression" logic for.

        # as in IssueStateManager.resolve(), but not because a reopened issue cannot be muted in principle (i.e. we
        # could mute it soon after reopening) but because when reopening an issue you're doing this from a resolved
        # state; calling unmute() here is done as an after-the-fact consistency-enforcement.
        IssueStateManager.unmute(issue)

    @staticmethod
    def mute(issue, unmute_on_volume_based_conditions="[]", unmute_after=None):
        if issue.is_resolved:
            raise IncongruentStateException("Cannot mute a resolved issue")

        issue.is_muted = True
        issue.unmute_on_volume_based_conditions = unmute_on_volume_based_conditions
        # 0 is "incorrect" but works just fine; it simply means that the first (real, but expensive) check is done
        # on-digest. However, to calculate the correct value we'd need to do that work right now, so postponing is
        # actually better. Setting to 0 is still needed to ensure the check is done when there was already a value.
        issue.next_unmute_check = 0

        if unmute_after is not None:
            issue.unmute_after = unmute_after

    @staticmethod
    def unmute(issue, triggering_event=None, unmute_metadata=None):
        if issue.is_muted:
            # we check on is_muted explicitly: it may be so that multiple unmute conditions happens simultaneously (and
            # not just in "funny configurations"). i.e. a single event could push you past more than 3 events per day or
            # 100 events per year. We don't want 2 "unmuted" alerts being sent in that case.

            issue.is_muted = False
            issue.unmute_on_volume_based_conditions = "[]"
            issue.unmute_after = None

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
                    issue=issue, triggering_event=triggering_event, timestamp=triggering_event.ingested_at,
                    kind=TurningPointKind.UNMUTED, metadata=json.dumps(unmute_metadata))
                triggering_event.never_evict = True  # .save() will be called by the caller of this function

    @staticmethod
    def get_unmute_thresholds(issue):
        unmute_vbcs = [
            VolumeBasedCondition.from_dict(vbc_s)
            for vbc_s in json.loads(issue.unmute_on_volume_based_conditions)
        ]

        # the for-loop in the below always contains 0 or 1 elements in our current UI (adding another unmute condition
        # for an already-muted issue is simply not possible) but would be robust for more elements.
        return [(vbc.period, vbc.nr_of_periods, vbc.volume) for vbc in unmute_vbcs]


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
            fixed_at=Concat(F("fixed_at"), Value(release_version + "\n")),
        )

        # release_version: str
        issue_qs.update(
            fixed_at=Concat(F("fixed_at"), Value(release_version + "\n")),
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
        if issue_qs.filter(is_resolved=True).exists():
            # we might remove this check for performance reasons later (it's more expensive here than in the non-bulk
            # case because we have to do a query to check for it). For now we leave it in to avoid surprises while we're
            # still heavily in development.
            raise IncongruentStateException("Cannot mute a resolved issue")

        issue_qs.update(
            is_muted=True,
            unmute_on_volume_based_conditions=unmute_on_volume_based_conditions,
            next_unmute_check=0,
        )

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
    triggering_event = models.ForeignKey("events.Event", blank=True, null=True, on_delete=models.DO_NOTHING)

    # null: the system-user
    user = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL)
    timestamp = models.DateTimeField(blank=False, null=False)  # this info is also in the event, but event is nullable
    kind = models.IntegerField(blank=False, null=False, choices=TurningPointKind.choices)
    metadata = models.TextField(blank=False, null=False, default="{}")  # json string
    comment = models.TextField(blank=True, null=False, default="")

    class Meta:
        # by ordering on "-id" we order things that happen in a single ingestion in the order in which they happened.
        # (in particular: NEXT_MATERIALIZED followed by REGRESSED is a common pattern)
        ordering = ["-timestamp", "-id"]
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
