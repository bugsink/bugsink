import json
from datetime import datetime, timezone

from projects.models import Project
from events.models import Event

from .period_counter import PeriodCounter
from .volume_based_condition import VolumeBasedCondition

from issues.models import Issue


_registry = None
UNMUTE_PURPOSE = "unmute"


def create_unmute_issue_handler(issue_id):
    def unmute():
        # we might just push this into a [class]method of Issue
        issue = Issue.objects.get(id=issue_id)

        if issue.is_muted:
            # we check on is_muted explicitly: it may be so that multiple unmute conditions happens simultaneously (and
            # not just in "funny configurations"). i.e. a single event could push you past more than 3 events per day or
            # 100 events per year. We don't want 2 "unmuted" alerts being sent in that case.

            issue.is_muted = False

            issue.unmute_on_volume_based_conditions = "[]"
            issue.save()

            # We keep the pc_registry and the value of issue.unmute_on_volume_based_conditions in-sync to avoid going
            # mad (in general). A specific case that I can think of off the top of my head that goes wrong if you
            # wouldn't do this, even given the fact that we check on is_muted in the above: you might re-mute but with
            # different unmute conditions, and in that case you don't want your old outdated conditions triggering
            # anything. (Side note: I'm not sure how I feel about reaching out to the global registry here; the
            # alternative would be to pass this along.)
            get_pc_registry().by_issue[issue_id].remove_event_listener(UNMUTE_PURPOSE)

    return unmute


class PeriodCounterRegistry(object):

    def __init__(self):
        self.by_project, self.by_issue = self.load_from_scratch(
            projects=Project.objects.all(),
            issues=Issue.objects.all(),
            ordered_events=Event.objects.all().order_by('server_side_timestamp'),
            now=datetime.now(timezone.utc),
        )

    @classmethod
    def load_from_scratch(self, projects, issues, ordered_events, now):
        # create period counters for all projects and issues
        by_project = {}
        by_issue = {}

        for project in projects:
            by_project[project.id] = PeriodCounter()

        for issue in issues:
            by_issue[issue.id] = PeriodCounter()

        # load all events (one by one, let's measure the slowness of the naive implementation before making it faster)
        for event in ordered_events:
            project_pc = by_project[event.project_id]
            project_pc.inc(event.timestamp)

            issue_pc = by_issue[event.issue_id]
            issue_pc.inc(event.timestamp)

        # connect all volume-based conditions to their respective period counters' event listeners
        # this is done after the events are loaded because:
        # 1. we don't actually want to trigger anything on-load and
        # 2. this is much faster.
        for issue in issues.filter(is_muted=True):
            issue_pc = by_issue[issue.id]

            unmute_vbcs = [
                VolumeBasedCondition.from_dict(vbc_s)
                for vbc_s in json.loads(issue.unmute_on_volume_based_conditions)
            ]

            for vbc in unmute_vbcs:
                issue_pc.add_event_listener(
                    period_name=vbc.period,
                    nr_of_periods=vbc.nr_of_periods,
                    gte_threshold=vbc.volume,
                    when_becomes_true=create_unmute_issue_handler(issue.id),
                    tup=now.timetuple(),
                    purpose=UNMUTE_PURPOSE,
                )

        return by_project, by_issue


def get_pc_registry():
    # lazy initialization; this is TSTTCPW for 'run once when the server starts'; it has the obvious drawback that it
    # slows down the first (handled) event. When we get to the "real gunicorn server" we should probably just hook into
    # gunicorn's events to initialize this
    # (note once you do this: don't hook into app-initialization; there you cannot expect to be running DB stuff)

    global _registry
    if _registry is None:
        _registry = PeriodCounterRegistry()
    return _registry


# some TODOs:
#
# * quotas (per project, per issue)
