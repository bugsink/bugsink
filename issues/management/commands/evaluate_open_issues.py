import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from bugsink.transaction import durable_atomic
from projects.models import Project
from issues.models import Issue, IssueStateManager, TurningPoint, TurningPointKind
from issues.realert import record_still_open, mute_with_volume_wake
from ingest.event_counter import filter_for_periods, get_total_events_in_period
from events.models import Event


def _open_issues(project):
    return Issue.objects.filter(project=project, is_resolved=False, is_muted=False, is_deleted=False)


def _is_quiet(issue, project, now):
    in_period = filter_for_periods(Event.objects.filter(issue=issue), project.noise_period, 1, now)
    return get_total_events_in_period(in_period) < project.mute_volume


def _remute_quiet(issue, project, now):
    # Re-mute an issue that has gone quiet, attaching the wake condition so it can unmute again. This is a state change,
    # so it gets a turning point; it deliberately sends no alert (an issue becoming quiet is not news).
    condition, mute_metadata = mute_with_volume_wake(project)
    IssueStateManager.mute(issue, unmute_on_volume_based_conditions=json.dumps([condition]))
    TurningPoint.objects.create(
        project_id=issue.project_id, issue=issue, timestamp=now,
        kind=TurningPointKind.MUTED, metadata=json.dumps(mute_metadata))
    issue.save()


def _should_realert_days(issue, project, now):
    reference = issue.last_realerted_at or issue.first_seen
    return (now - reference).days >= project.realert_after_days


class Command(BaseCommand):
    help = (
        "Apply the time-based parts of the issue noise policy: re-mute issues that have gone quiet and remind about "
        "issues that stay open. Meant to run periodically from cron (snappea has no scheduler of its own).")

    def handle(self, *args, **options):
        # One windowed count query per open issue (O(n)). Fine for a periodic sweep over the open set; if a project
        # ever has so many open issues that this drags, batch the counts into a single grouped query per project.
        now = timezone.now()

        # re-mute quiet issues; both ends of the band are required so a re-muted issue can still wake back up
        for project in Project.objects.filter(mute_volume__gt=0, unmute_volume__gt=0):
            for issue in _open_issues(project):
                if _is_quiet(issue, project, now):
                    with durable_atomic():
                        _remute_quiet(issue, project, now)

        # remind about issues that have stayed open; the re-mute pass above already dropped the quiet ones
        for project in Project.objects.filter(realert_after_days__gt=0):
            for issue in _open_issues(project):
                if _should_realert_days(issue, project, now):
                    with durable_atomic():
                        record_still_open(issue, None, now)
                        issue.save()
