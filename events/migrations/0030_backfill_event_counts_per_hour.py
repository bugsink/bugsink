# Backfill the new reporting buckets from retained Event rows.
#
# This uses the same idea as the quota code: use digest-order differences rather than raw retained-row counts. This can
# still not reconstruct everything:
# * if a bucket has no retained events at all, we cannot reconstruct that hour.
# * if only middle events remain, the digest-order delta recovers deleted/evicted events between them.
# * if deleted/evicted events were only before the first retained event or after the last retained event inside that hour,
#   we still undercount.
# Future accepted events are complete from the moment this migration has run.

from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import migrations
from django.db.models.functions import TruncHour


BATCH_SIZE = 1000
EVENT_COUNTS_PER_HOUR_MAX_AGE = timedelta(days=90)


def _bulk_create(model, rows):
    batch = []
    for row in rows:
        batch.append(model(**row))
        if len(batch) >= BATCH_SIZE:
            model.objects.bulk_create(batch)
            batch = []

    if batch:
        model.objects.bulk_create(batch)


def get_total_events_in_period(qs_for_period, order_field, add_for_current=0):
    # Copied from ingest.event_counter.get_total_events_in_period, but made generic for project and issue digest orders.
    first_in_period = (
        qs_for_period.exclude(**{f"{order_field}__isnull": True})
        .order_by("digested_at", order_field).first())

    if first_in_period is None:
        return add_for_current
    elif getattr(first_in_period, order_field) is None:
        # Fall back to the pre-project_digest_order behavior.
        return qs_for_period.count() + add_for_current
    else:
        # will exist (implied by 'first'), and will have a digest-order value (because only _older_ might not)
        last_in_period = (qs_for_period.exclude(**{f"{order_field}__isnull": True})
                          .order_by("-digested_at", f"-{order_field}").first())

        return (getattr(last_in_period, order_field) - getattr(first_in_period, order_field)
                + 1 + add_for_current)  # +1: not the difference, but the count incl. both ends


def get_total_events_in_period_and_digest_order(qs_for_period):
    first_in_period = qs_for_period.order_by("digested_at", "digest_order").first()
    if first_in_period is None:
        return 0, None

    last_in_period = qs_for_period.order_by("-digested_at", "-digest_order").first()
    return (
        last_in_period.digest_order - first_in_period.digest_order + 1,
        last_in_period.digest_order,
    )


def _hour_qs(Event, bucket):
    return Event.objects.filter(digested_at__gte=bucket, digested_at__lt=bucket + timedelta(hours=1))


def _hourly_groups(hourly_events, *fields):
    return hourly_events.values(*fields, "bucket").order_by(*fields, "bucket").distinct()


def backfill_event_counts_per_hour(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    InstallationEventCountsPerHour = apps.get_model("events", "InstallationEventCountsPerHour")
    ProjectEventCountsPerHour = apps.get_model("events", "ProjectEventCountsPerHour")
    IssueEventCountsPerHour = apps.get_model("events", "IssueEventCountsPerHour")

    cutoff = (
        datetime.now(dt_timezone.utc).replace(minute=0, second=0, microsecond=0) - EVENT_COUNTS_PER_HOUR_MAX_AGE
    )

    # DB datetimes represent UTC instants; pass UTC explicitly so bucketing is independent of active timezone settings.
    hourly_events = Event.objects.filter(digested_at__gte=cutoff).annotate(
        bucket=TruncHour("digested_at", tzinfo=dt_timezone.utc))

    installation_counts = {}
    project_rows = []
    for row in _hourly_groups(hourly_events, "project_id"):
        count = get_total_events_in_period(
            _hour_qs(Event, row["bucket"]).filter(project_id=row["project_id"]),
            "project_digest_order",
        )
        if count == 0:
            continue

        project_rows.append({"project_id": row["project_id"], "bucket": row["bucket"], "count": count})
        installation_counts[row["bucket"]] = installation_counts.get(row["bucket"], 0) + count

    _bulk_create(
        ProjectEventCountsPerHour,
        project_rows,
    )

    _bulk_create(
        InstallationEventCountsPerHour,
        (
            {"bucket": bucket, "count": count}
            for bucket, count in sorted(installation_counts.items())
        ),
    )

    issue_rows = []
    for row in _hourly_groups(hourly_events, "project_id", "issue_id"):
        count, digest_order = get_total_events_in_period_and_digest_order(
            _hour_qs(Event, row["bucket"]).filter(issue_id=row["issue_id"]),
        )
        if count == 0:
            continue

        issue_rows.append({
            "project_id": row["project_id"],
            "issue_id": row["issue_id"],
            "bucket": row["bucket"],
            "count": count,
            "digest_order": digest_order,
        })

    _bulk_create(
        IssueEventCountsPerHour,
        issue_rows,
    )


def unbackfill_event_counts_per_hour(apps, schema_editor):
    apps.get_model("events", "InstallationEventCountsPerHour").objects.all().delete()
    apps.get_model("events", "ProjectEventCountsPerHour").objects.all().delete()
    apps.get_model("events", "IssueEventCountsPerHour").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0029_event_counts_per_hour_models"),
    ]

    operations = [
        migrations.RunPython(backfill_event_counts_per_hour, unbackfill_event_counts_per_hour),
    ]
