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


_NICE_Y_LABEL_STEPS = (1, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 12.5)
_NICE_Y_LABEL_STEP_RANK = {
    1: 0,
    2: 0.02,
    2.5: 0.08,
    5: 0.1,
    10: 0.1,
    3: 0.2,
    4: 0.25,
    6: 0.35,
    8: 0.55,
    12.5: 0.7,
    12: 0.8,
}


def _clean_label_value(value):
    value = round(value, 10)
    if math.isclose(value, round(value)):
        return int(round(value))
    return value


def _nice_base(value):
    if value == 0:
        return 1

    power = 10 ** math.floor(math.log10(abs(value)))
    scaled = value / power
    return min(_NICE_Y_LABEL_STEPS, key=lambda candidate: abs(candidate - scaled))


def _score_y_label_candidate(labels, step_base, max_value, max_labels):
    top = labels[0]
    count = len(labels)
    headroom = (top - max_value) / max(max_value, 1)
    if top - max_value <= 1:
        headroom = 0
    missing_labels = (max_labels - count) / max(max_labels - 1, 1)
    is_exact = math.isclose(top, max_value)

    return (
        headroom * 3.65
        + missing_labels * 2.8
        + _NICE_Y_LABEL_STEP_RANK[step_base] * 2.35
        + _NICE_Y_LABEL_STEP_RANK[_nice_base(top)] * 1.1
        - count / max_labels * 1.25
        - is_exact * 0.2
        + max(0, headroom - 0.2) * 6.25
        + max(0, headroom - 0.5) * 10.5
    )


def _get_y_label_candidates(max_value, max_labels):
    candidates = []
    seen = set()
    wants_integer_labels = float(max_value).is_integer()
    raw_step = max_value / (max_labels - 1)
    first_power = math.floor(math.log10(raw_step)) - 2
    last_power = math.floor(math.log10(max_value)) + 2

    for exponent in range(first_power, last_power + 1):
        power = 10 ** exponent
        for step_base in _NICE_Y_LABEL_STEPS:
            step = step_base * power
            first_interval = math.ceil(max_value / step - 1e-12)
            last_interval = 1 if max_labels == 2 else max_labels - 1
            for intervals in range(max(1, first_interval), last_interval + 1):
                labels = [
                    _clean_label_value(i * step)
                    for i in range(intervals, -1, -1)
                ]
                if wants_integer_labels and any(not isinstance(label, int) for label in labels):
                    continue

                labels_tuple = tuple(labels)
                if labels_tuple in seen:
                    continue

                seen.add(labels_tuple)
                candidates.append((labels, step_base))

    return candidates


def get_y_labels(max_value, max_labels=5):
    if max_labels <= 0:
        return []

    if max_labels == 1:
        return [_clean_label_value(max(1, max_value))]

    if max_value <= 1:
        return [1, 0]

    if float(max_value).is_integer() and max_value <= max_labels - 1:
        return reversed(range(int(max_value) + 1))

    candidates = _get_y_label_candidates(max_value, max_labels)
    if max_labels == 2:
        return min(candidates, key=lambda candidate: candidate[0][0])[0]

    return min(
        candidates,
        key=lambda candidate: _score_y_label_candidate(candidate[0], candidate[1], max_value, max_labels),
    )[0]


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
    assert_(now.tzinfo == dt_timezone.utc)
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

    # Per-chart scaling keeps low-volume rows readable instead of squashing them against a page-wide outlier.
    # Floor at 10 so a single event does not render as a full-height spike.
    max_value = max(10, max(buckets))
    total = sum(buckets)
    title = f"{_format_event_count(total)} in the past 24h"
    for bucket in event_buckets:
        bucket["pct"] = (bucket["count"] / max_value) * 100
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

    max_value = max(10, max(buckets))
    bar_data = [(v / max_value) * 100 for v in buckets]

    for bucket, pct in zip(event_buckets, bar_data, strict=True):
        bucket["pct"] = pct
        bucket["has_overlay"] = has_overlay
        if has_overlay:
            bucket["matching_pct"] = (bucket["matching_count"] / max_value) * 100
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
