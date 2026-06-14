from datetime import timedelta, timezone as dt_timezone

from django.db.models import F

from bugsink.utils import assert_

from .models import InstallationEventCountsPerHour, IssueEventCountsPerHour, ProjectEventCountsPerHour


EVENT_COUNTS_PER_HOUR_MAX_AGE = timedelta(days=90)


def hour_bucket(dt):
    return dt.astimezone(dt_timezone.utc).replace(minute=0, second=0, microsecond=0)


def _remove_stale_event_count_buckets(bucket):
    cutoff = bucket - EVENT_COUNTS_PER_HOUR_MAX_AGE
    InstallationEventCountsPerHour.objects.filter(bucket__lt=cutoff).delete()
    ProjectEventCountsPerHour.objects.filter(bucket__lt=cutoff).delete()
    IssueEventCountsPerHour.objects.filter(bucket__lt=cutoff).delete()


def _increment(model, remove_stale_on_create=False, **kwargs):
    if model.objects.filter(**kwargs).update(count=F("count") + 1) > 0:
        # the return-value of update() is the number of rows updated, if it's > 0, we're done here.
        return

    # otherwise, create a new record with count=1. No need for try/except here b/c we have single-writer architecture
    model.objects.create(**kwargs, count=1)

    if remove_stale_on_create:
        _remove_stale_event_count_buckets(kwargs["bucket"])


def record_event_counts(project, issue, digested_at):
    assert_(digested_at.tzinfo == dt_timezone.utc)

    bucket = hour_bucket(digested_at)

    # when a new Installation-wide bucket is created (hourly threshold is crossed), we also remove stale buckets
    _increment(InstallationEventCountsPerHour, remove_stale_on_create=True, bucket=bucket)
    _increment(ProjectEventCountsPerHour, project=project, bucket=bucket)
    _increment(IssueEventCountsPerHour, project=project, issue=issue, bucket=bucket)
