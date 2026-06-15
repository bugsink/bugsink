import math
from datetime import timedelta, timezone

from events.models import IssueEventCountsPerHour


def get_sparkline_range(now):
    # align on 4-hour boundary; round up from now
    now = now.astimezone(timezone.utc)
    hour_step = 4
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


def get_issue_event_sparkline(issue_id, now):
    start, end, interval = get_sparkline_range(now)

    bucket_edges = []
    curr = start
    while curr <= end:
        bucket_edges.append(curr)
        curr += interval

    buckets = []
    event_buckets = []
    for i in range(1, len(bucket_edges)):
        count = IssueEventCountsPerHour.objects.filter(
            issue_id=issue_id,
            bucket__gte=bucket_edges[i - 1],
            bucket__lt=bucket_edges[i],
        ).values_list("count", flat=True)
        count = sum(count)
        buckets.append(count)
        bucket_start = bucket_edges[i - 1]
        bucket_end = bucket_edges[i]
        event_buckets.append({
            "bucket_start": bucket_start,
            "bucket_end": bucket_end,
            "count": count,
            "label": f"{bucket_start.day} {bucket_start:%b %H:%M} - {bucket_end:%H:%M}",
        })

    max_value = max(buckets) or 0
    if max_value == 0:
        bar_data = [0 for v in buckets]
    else:
        bar_data = [(v / max_value) * 100 for v in buckets]

    for bucket, pct in zip(event_buckets, bar_data, strict=True):
        bucket["pct"] = pct

    return {
        "bar_data": bar_data,
        "buckets": buckets,
        "event_buckets": event_buckets,
        "x_labels": get_x_labels(start, end),
        "y_labels": get_y_labels(max_value, 4),
    }
