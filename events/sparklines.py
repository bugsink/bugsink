import math
from datetime import timedelta, timezone

from django.db.models import Count, Max
from django.db.models.functions import TruncHour

from bugsink.utils import assert_
from events.models import IssueEventCountsPerHour


def get_sparkline_range(now, hour_step=6):
    # align on the display bucket boundary; round up from now
    assert_(now.tzinfo == timezone.utc)
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


def _format_event_count(count):
    return f"{count:,} event" if count == 1 else f"{count:,} events"


def _get_bucket_title(label, count, matching_count):
    if matching_count is None:
        return f"{label}: {_format_event_count(count)}"

    matching = f"{matching_count:,} matching event{'' if matching_count == 1 else 's'}"
    return f"{label}: {matching}, {_format_event_count(count)} total"


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
        assert_(active_event_digested_at.tzinfo == timezone.utc)

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
                bucket=TruncHour("digested_at", tzinfo=timezone.utc),
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
