from datetime import datetime, timezone
import json
import uuid

from django.db import models

from alerts.tasks import send_unmute_alert

from bugsink.volume_based_condition import VolumeBasedCondition


class Issue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    project = models.ForeignKey(
        "projects.Project", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    hash = models.CharField(max_length=32, blank=False, null=False)

    # fields related to resolution:
    # what does this mean for the release-based use cases? it means what you filter on.
    # it also simply means: it was "marked as resolved" after the last regression (if any)
    is_resolved = models.BooleanField(default=False)
    is_resolved_by_next_release = models.BooleanField(default=False)
    fixed_at = models.TextField(blank=False, null=False, default='[]')
    events_at = models.TextField(blank=False, null=False, default='[]')

    is_muted = models.BooleanField(default=False)
    unmute_on_volume_based_conditions = models.TextField(blank=False, null=False, default="[]")  # json string

    def get_absolute_url(self):
        return f"/issues/issue/{ self.id }/event/last/"

    def parsed_data(self):
        # TEMP solution; won't scale
        return json.loads(self.events.first().data)

    def get_main_exception(self):
        # TODO: refactor (its usages) to a (filled-on-create) field

        # Note: first event, last exception

        # We call the last exception in the chain the main exception because it's the one you're most likely to care
        # about. I'd roughly distinguish 2 cases for reraising:
        #
        # 1. intentionally rephrasing/retyping exceptions to more clearly express their meaning. In that case you
        #    certainly care more about the rephrased thing than the original, that's the whole point.
        #
        # 2. actual "accidents" happening while error-handling. In that case you care about the accident first (bugsink
        #    is a system to help you think about cases that you didn't properly think about in the first place),
        #    although you may also care about the root cause. (In fact, sometimes you care more about the root cause,
        #    but I'd say you'll have to yak-shave your way there).

        parsed_data = json.loads(self.events.first().data)
        exc = parsed_data.get("exception", {"values": []})
        values = exc["values"]  # required by the json spec, so can be done safely
        return values[-1] if values else {}

    def title(self):
        # TODO: refactor to a (filled-on-create) field
        main_exception = self.get_main_exception()
        return main_exception.get("type", "none") + ": " + main_exception.get("value", "none")

    def get_fixed_at(self):
        return json.loads(self.fixed_at)

    def get_events_at(self):
        return json.loads(self.events_at)

    def add_fixed_at(self, release):
        fixed_at = self.get_fixed_at()
        if release.version not in fixed_at:
            fixed_at.append(release.version)
            self.fixed_at = json.dumps(fixed_at)

    def occurs_in_last_release(self):
        return False  # TODO actually implement (and then: implement in a performant manner)


class IssueStateManager(object):
    """basically: a namespace; with static methods that combine field-setting in a single place"""

    # NOTE I'm not so sure about the exact responsibilities of this thingie yet. In particular:
    # * save() is now done outside;
    # * alerts are sent from inside.

    @staticmethod
    def resolve(issue):
        issue.is_resolved = True

        # an issue cannot be both resolved and muted; muted means "the problem persists but don't tell me about it
        # (or maybe unless some specific condition happens)" and resolved means "the problem is gone". Hence, resolving
        # an issue means unmuting it.
        IssueStateManager.unmute(issue, implicitly_called=True)

    @staticmethod
    def resolve_by_latest(issue):
        issue.is_resolved = True
        issue.add_fixed_at(issue.project.get_latest_release())
        IssueStateManager.unmute(issue, implicitly_called=True)  # as in IssueStateManager.resolve()

    @staticmethod
    def resolve_by_next(issue):
        issue.is_resolved = True
        issue.is_resolved_by_next_release = True
        IssueStateManager.unmute(issue, implicitly_called=True)  # as in IssueStateManager.resolve()

    @staticmethod
    def reopen(issue):
        issue.is_resolved = False
        issue.is_resolved_by_next_release = False  # ?? echt?
        # TODO and what about fixed_at ?

        # as in IssueStateManager.resolve(), but not because a reopened issue cannot be muted (we could mute it soon
        # after reopening) but because when reopening an issue you're doing this from a resolved state; calling unmute()
        # here is done as a consistency-enforcement after the fact.
        IssueStateManager.unmute(issue, implicitly_called=True)

    @staticmethod
    def mute(issue, unmute_on_volume_based_conditions="[]"):
        from bugsink.registry import get_pc_registry  # avoid circular import
        now = datetime.now(timezone.utc)  # NOTE: clock-reading going on here... should it be passed-in?

        issue.is_muted = True
        issue.unmute_on_volume_based_conditions = unmute_on_volume_based_conditions

        IssueStateManager.set_unmute_handlers(get_pc_registry().by_issue, issue, now)

    @staticmethod
    def unmute(issue, implicitly_called=False):
        # implicitly_called is used to avoid sending an unmute alert when the unmute is triggered by one of the other
        # methods in this class.

        from bugsink.registry import get_pc_registry, UNMUTE_PURPOSE  # avoid circular import

        if issue.is_muted:
            # we check on is_muted explicitly: it may be so that multiple unmute conditions happens simultaneously (and
            # not just in "funny configurations"). i.e. a single event could push you past more than 3 events per day or
            # 100 events per year. We don't want 2 "unmuted" alerts being sent in that case.

            issue.is_muted = False
            issue.unmute_on_volume_based_conditions = "[]"

            # We keep the pc_registry and the value of issue.unmute_on_volume_based_conditions in-sync to avoid going
            # mad (in general). A specific case that I can think of off the top of my head that goes wrong if you
            # wouldn't do this, even given the fact that we check on is_muted in the above: you might re-mute but with
            # different unmute conditions, and in that case you don't want your old outdated conditions triggering
            # anything. (Side note: I'm not sure how I feel about reaching out to the global registry here; the
            # alternative would be to pass this along.)
            # (NOTE: upon rereading the above, it seems kind of trivial: a cache should simply be in-sync, no further
            # thinking is needed)
            get_pc_registry().by_issue[issue.id].remove_event_listener(UNMUTE_PURPOSE)

            if not implicitly_called:
                # (note: we can expect project to be set, because it will be None only when projects are deleted, in
                # which case no more unmuting happens)
                if issue.project.alert_on_unmute:
                    send_unmute_alert.delay(issue.id)

    @staticmethod
    def set_unmute_handlers(by_issue, issue, now):
        from bugsink.registry import UNMUTE_PURPOSE  # avoid circular import
        issue_pc = by_issue[issue.id]

        unmute_vbcs = [
            VolumeBasedCondition.from_dict(vbc_s)
            for vbc_s in json.loads(issue.unmute_on_volume_based_conditions)
        ]

        for vbc in unmute_vbcs:
            initial_state = issue_pc.add_event_listener(
                period_name=vbc.period,
                nr_of_periods=vbc.nr_of_periods,
                gte_threshold=vbc.volume,
                when_becomes_true=create_unmute_issue_handler(issue.id),
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


def create_unmute_issue_handler(issue_id):
    def unmute():
        issue = Issue.objects.get(id=issue_id)
        IssueStateManager.unmute(issue)
        issue.save()

    return unmute
