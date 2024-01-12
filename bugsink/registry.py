from datetime import datetime, timezone

from projects.models import Project
from events.models import Event
from issues.models import Issue, IssueStateManager

from .period_counter import PeriodCounter


_registry = None
UNMUTE_PURPOSE = "unmute"


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
            IssueStateManager.set_unmute_handlers(by_issue, issue, now)

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


def reset_pc_registry():
    # needed for tests
    global _registry
    _registry = None


# some TODOs:
#
# * quotas (per project, per issue)
