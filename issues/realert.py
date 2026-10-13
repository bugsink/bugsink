import json

from bugsink.transaction import delay_on_commit
from alerts.tasks import send_still_open_alert

from .models import TurningPoint, TurningPointKind


def _crossed_bucket(previous_value, current_value, bucket_size):
    # True when going from previous_value to current_value crosses a multiple of bucket_size. bucket_size 0 disables.
    return bucket_size > 0 and current_value // bucket_size > previous_value // bucket_size


def mute_with_volume_wake(project):
    # The wake condition for a project's noise band, as (VolumeBasedCondition dict, MUTED turning-point metadata). Built
    # in one place so the stored condition and the history label can't drift apart: the condition uses the
    # VolumeBasedCondition keys (period/nr_of_periods/volume); the metadata uses the keys the history renderer reads
    # (period_name/nr_of_periods/volume).
    condition = {"period": project.noise_period, "nr_of_periods": 1, "volume": project.unmute_volume}
    metadata = {"mute_until": {
        "period_name": project.noise_period, "nr_of_periods": 1, "volume": project.unmute_volume}}
    return condition, metadata


def record_still_open(issue, triggering_event, now):
    # Record a "still open" reminder: a turning point in the issue history (so the reminder is traceable, like every
    # other state note) plus the existing alert. Does not save the issue; the caller does.
    note = "This issue is still open: %d events since it was first seen." % issue.digested_event_count
    TurningPoint.objects.create(
        project_id=issue.project_id, issue=issue, triggering_event=triggering_event, timestamp=now,
        kind=TurningPointKind.STILL_OPEN, metadata=json.dumps({"digested_event_count": issue.digested_event_count}))
    if triggering_event is not None:
        triggering_event.never_evict = True
    issue.last_realerted_at = now
    delay_on_commit(send_still_open_alert, str(issue.id), note)


def maybe_realert_on_events(issue, project, triggering_event, now):
    # On-ingest reminder: fire when an open issue's event count crosses a multiple of realert_after_events.
    if issue.is_muted or issue.is_resolved:
        return
    if not _crossed_bucket(issue.digested_event_count - 1, issue.digested_event_count, project.realert_after_events):
        return
    record_still_open(issue, triggering_event, now)
