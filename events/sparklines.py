import math
from datetime import timedelta, timezone

from events.models import IssueEventCountsPerHour


def get_sparkline_range(now, hour_step=6):
    # align on the display bucket boundary; round up from now
    now = now.astimezone(timezone.utc)
    boundary = math.ceil(now.hour / hour_step) * hour_step
    end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=boundary)

    start = end - timedelta(days=28)
    interval = timedelta(hours=hour_step)
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
    if bucket_start.hour == 0 and bucket_start.minute == 0 and bucket_end == bucket_start + timedelta(days=1):
        return f"{bucket_start.day} {bucket_start:%b}"

    if bucket_start.date() == bucket_end.date():
        return f"{bucket_start.day} {bucket_start:%b %H:%M} - {bucket_end:%H:%M}"

    return f"{bucket_start.day} {bucket_start:%b %H:%M} - {bucket_end.day} {bucket_end:%b %H:%M}"


def _get_bucket_edges(start, end, interval):
    bucket_edges = []
    curr = start
    while curr <= end:
        bucket_edges.append(curr)
        curr += interval

    return bucket_edges


def _build_variant(start, end, interval, buckets_by_hour, active_event_digested_at):
    bucket_edges = _get_bucket_edges(start, end, interval)

    buckets = []
    event_buckets = []
    for i in range(1, len(bucket_edges)):
        bucket_start = bucket_edges[i - 1]
        bucket_end = bucket_edges[i]
        count = 0
        digest_order = None
        curr = bucket_start
        while curr < bucket_end:
            hour_bucket = buckets_by_hour.get(curr)
            if hour_bucket is not None:
                count += hour_bucket["count"]
                digest_order = hour_bucket["digest_order"]
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
            "digest_order": digest_order,
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

    return {
        "interval_hours": int(interval / timedelta(hours=1)),
        "bar_data": bar_data,
        "buckets": buckets,
        "event_buckets": event_buckets,
        "x_labels": get_x_labels(start, end),
        "y_labels": get_y_labels(max_value, 4),
    }


def get_issue_event_sparkline(issue_id, now, active_event_digested_at=None):
    if active_event_digested_at is not None:
        active_event_digested_at = active_event_digested_at.astimezone(timezone.utc)

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

    for start, end, interval in ranges:
        variants.append(_build_variant(start, end, interval, buckets_by_hour, active_event_digested_at))

    large_variant = variants[-1]
    return {
        **large_variant,
        "variants": variants,
    }
