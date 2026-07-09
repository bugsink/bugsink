import math
from datetime import timedelta, timezone as dt_timezone

from django.db.models import Count, Max
from django.db.models.functions import TruncHour
from django.utils import timezone

from bugsink.utils import assert_
from events.models import InstallationEventCountsPerHour, IssueEventCountsPerHour, ProjectEventCountsPerHour
from events.usage import hour_bucket


def _installation_localtime(dt):
    return timezone.localtime(dt, timezone.get_default_timezone())


def _as_utc(dt):
    return dt.astimezone(dt_timezone.utc)


def get_sparkline_range(now, hour_step=6, days=28):
    # Align display buckets on installation-local boundaries; stored hourly buckets remain UTC.
    assert_(now.tzinfo == dt_timezone.utc)
    local_now = _installation_localtime(now)
    interval = timedelta(hours=hour_step)
    local_start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    boundary = math.ceil((local_now - local_start_of_day) / interval) * interval
    local_end = local_start_of_day + boundary

    start = _as_utc(local_end - timedelta(days=days))
    end = _as_utc(local_end)
    return start, end, interval


def get_x_labels(start, end, num_labels=5):
    labels = []
    for i in range(num_labels):
        labels.append(start + i * (end - start) / (num_labels - 1))

    return labels


def get_y_labels(max_value, num_labels=5):
    if max_value == 0:
        return [1, 0]

    # the available number of non-zero labels
    available_labels = num_labels - 1

    if max_value <= available_labels:
        return reversed(list(range(0, max_value + 1)))

    step = max_value / available_labels

    # convert step into a round number:
    magnitude = 10 ** (len(str(math.ceil(step))) - 1)
    step = math.ceil(step / magnitude) * magnitude

    labels = [0]
    for i in range(1, num_labels):
        labels.append(labels[-1] + step)

    return reversed(labels)


def _format_bucket_label(bucket_start, bucket_end):
    bucket_start = _installation_localtime(bucket_start)
    bucket_end = _installation_localtime(bucket_end)

    if bucket_start.hour == 0 and bucket_start.minute == 0 and bucket_end == bucket_start + timedelta(days=1):
        return f"{bucket_start.day} {bucket_start:%b}"

    if bucket_start.date() == bucket_end.date():
        return f"{bucket_start.day} {bucket_start:%b %H:%M} - {bucket_end:%H:%M}"

    return f"{bucket_start.day} {bucket_start:%b %H:%M} - {bucket_end.day} {bucket_end:%b %H:%M}"


def _get_bucket_edges(start, end, interval):
    bucket_edges = []
    curr = _installation_localtime(start)
    local_end = _installation_localtime(end)
    while curr <= local_end:
        bucket_edges.append(_as_utc(curr))
        curr += interval

    return bucket_edges


def _format_event_count(count):
    return f"{count:,} event" if count == 1 else f"{count:,} events"


def _get_bucket_title(label, count, matching_count):
    if matching_count is None:
        return f"{label}: {_format_event_count(count)}"

    matching = f"{matching_count:,} matching event{'' if matching_count == 1 else 's'}"
    return f"{label}: {matching}, {_format_event_count(count)} total"


# Compact list sparklines: 24 hourly buckets for issue/project rows, loaded in one batched query per list.
def _get_list_sparkline_range(now):
    assert_(now.tzinfo == timezone.utc)
    current_hour = hour_bucket(now)
    return current_hour - timedelta(hours=23), current_hour + timedelta(hours=1), timedelta(hours=1)


def _build_compact_hourly_series(now, buckets_by_hour):
    start, end, interval = _get_list_sparkline_range(now)
    current_hour = hour_bucket(now)
    buckets = []
    event_buckets = []
    curr = start
    while curr < end:
        bucket_end = curr + interval
        count = buckets_by_hour.get(curr, 0)
        buckets.append(count)
        event_buckets.append({
            "bucket_start": curr,
            "bucket_end": bucket_end,
            "count": count,
            "is_current_hour": curr == current_hour,
        })
        curr = bucket_end

    raw_max_value = max(buckets) or 0
    # Per-chart scaling keeps low-volume rows readable instead of squashing them against a page-wide outlier.
    # Floor at 10 so a single event does not render as a full-height spike.
    max_value = max(10, raw_max_value) if raw_max_value else 0
    total = sum(buckets)
    title = f"{_format_event_count(total)} in the past 24h"
    for bucket in event_buckets:
        bucket["pct"] = (bucket["count"] / max_value) * 100 if max_value else 0
        bucket["title"] = title

    return {
        "event_buckets": event_buckets,
        "total": total,
        "total_label": _format_event_count(total),
        "title": title,
    }


def _get_list_sparklines(ids, now, model, id_field, extra_filters=None):
    if not ids:
        return {}

    start, end, _ = _get_list_sparkline_range(now)
    filters = {
        f"{id_field}__in": ids,
        "bucket__gte": start,
        "bucket__lt": end,
    }
    if extra_filters is not None:
        filters.update(extra_filters)

    buckets_by_id = {id_: {} for id_ in ids}
    for id_, bucket, count in model.objects.filter(**filters).values_list(id_field, "bucket", "count"):
        buckets_by_id[id_][bucket] = count

    return {
        id_: _build_compact_hourly_series(now, buckets_by_hour)
        for id_, buckets_by_hour in buckets_by_id.items()
    }


def get_issue_list_event_sparklines(issue_ids, now, project_id=None):
    extra_filters = {"project_id": project_id} if project_id is not None else None
    return _get_list_sparklines(issue_ids, now, IssueEventCountsPerHour, "issue_id", extra_filters)


def get_project_list_event_sparklines(project_ids, now):
    return _get_list_sparklines(project_ids, now, ProjectEventCountsPerHour, "project_id")


def _build_sized_bucket_series(
        start, end, interval, buckets_by_hour, matching_buckets_by_hour, active_event_digested_at):
    bucket_edges = _get_bucket_edges(start, end, interval)

    buckets = []
    event_buckets = []
    has_overlay = matching_buckets_by_hour is not None
    for i in range(1, len(bucket_edges)):
        bucket_start = bucket_edges[i - 1]
        bucket_end = bucket_edges[i]
        count = 0
        digest_order = None
        matching_count = 0
        matching_digest_order = None
        curr = bucket_start
        while curr < bucket_end:
            hour_bucket = buckets_by_hour.get(curr)
            if hour_bucket is not None:
                count += hour_bucket["count"]
                digest_order = hour_bucket["digest_order"]
            if matching_buckets_by_hour is not None:
                matching_hour_bucket = matching_buckets_by_hour.get(curr)
                if matching_hour_bucket is not None:
                    matching_count += matching_hour_bucket["count"]
                    if (matching_digest_order is None or
                            matching_hour_bucket["digest_order"] > matching_digest_order):
                        matching_digest_order = matching_hour_bucket["digest_order"]
            curr += timedelta(hours=1)

        contains_active_event = (
            active_event_digested_at is not None and
            bucket_start <= active_event_digested_at < bucket_end
        )

        buckets.append(count)
        event_buckets.append({
            "bucket_start": bucket_start,
            "bucket_end": bucket_end,
            "count": count,
            "digest_order": matching_digest_order if has_overlay else digest_order,
            "matching_count": matching_count if has_overlay else None,
            "label": _format_bucket_label(bucket_start, bucket_end),
            "contains_active_event": contains_active_event,
        })

    max_value = max(buckets) or 0
    if max_value == 0:
        bar_data = [0 for v in buckets]
    else:
        bar_data = [(v / max_value) * 100 for v in buckets]

    for bucket, pct in zip(event_buckets, bar_data, strict=True):
        bucket["pct"] = pct
        bucket["has_overlay"] = has_overlay
        if has_overlay:
            bucket["matching_pct"] = (bucket["matching_count"] / max_value) * 100 if max_value else 0
            bucket["click_count"] = bucket["matching_count"]
        else:
            bucket["matching_pct"] = None
            bucket["click_count"] = bucket["count"]
        bucket["title"] = _get_bucket_title(bucket["label"], bucket["count"], bucket["matching_count"])

    return {
        "interval_hours": int(interval / timedelta(hours=1)),
        "bar_data": bar_data,
        "buckets": buckets,
        "event_buckets": event_buckets,
        "x_labels": get_x_labels(start, end),
        "y_labels": get_y_labels(max_value, 4),
    }


def get_issue_event_sparkline(issue_id, now, active_event_digested_at=None, matching_event_qs=None):
    if active_event_digested_at is not None:
        assert_(active_event_digested_at.tzinfo == dt_timezone.utc)

    variants = []
    ranges = []
    for hour_step in (24, 12, 6):
        start, end, interval = get_sparkline_range(now, hour_step=hour_step)
        ranges.append((start, end, interval))

    query_start = min(start for start, _, _ in ranges)
    query_end = max(end for _, end, _ in ranges)
    buckets_by_hour = {
        bucket: {"count": count, "digest_order": digest_order}
        for bucket, count, digest_order in IssueEventCountsPerHour.objects.filter(
            issue_id=issue_id,
            bucket__gte=query_start,
            bucket__lt=query_end,
        ).values_list("bucket", "count", "digest_order")
    }

    matching_buckets_by_hour = None
    if matching_event_qs is not None:
        # Search is dynamic, so these counts can only cover retained events that still have searchable rows. This also
        # means q=<matches everything> can show retained events as an overlay on top of observed bucket counts, while
        # the case where q=<empty> shows the buckets fully hightlighted. We accept that asymmetry for performance.
        matching_buckets_by_hour = {
            bucket: {"count": count, "digest_order": digest_order}
            for bucket, count, digest_order in matching_event_qs.filter(
                digested_at__gte=query_start,
                digested_at__lt=query_end,
            ).annotate(
                bucket=TruncHour("digested_at", tzinfo=dt_timezone.utc),
            ).values("bucket").annotate(
                count=Count("id"),
                matching_digest_order=Max("digest_order"),
            ).values_list("bucket", "count", "matching_digest_order")
        }

    for start, end, interval in ranges:
        variants.append(_build_sized_bucket_series(start, end, interval, buckets_by_hour, matching_buckets_by_hour,
                                                   active_event_digested_at))

    large_variant = variants[-1]
    return {
        **large_variant,
        "variants": variants,
    }


def get_installation_event_sparkline(now):
    variants = []
    ranges = []
    for hour_step in (24, 12, 6):
        start, end, interval = get_sparkline_range(now, hour_step=hour_step, days=30)
        ranges.append((start, end, interval))

    query_start = min(start for start, _, _ in ranges)
    query_end = max(end for _, end, _ in ranges)
    buckets_by_hour = {
        bucket: {"count": count, "digest_order": None}
        for bucket, count in InstallationEventCountsPerHour.objects.filter(
            bucket__gte=query_start,
            bucket__lt=query_end,
        ).values_list("bucket", "count")
    }

    for start, end, interval in ranges:
        variants.append(_build_sized_bucket_series(start, end, interval, buckets_by_hour, None, None))

    large_variant = variants[-1]
    return {
        **large_variant,
        "variants": variants,
    }
