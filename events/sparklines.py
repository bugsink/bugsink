import math
from events.models import Event


def _last_digest_order_before(moment, qs_base):
    row = qs_base.filter(digested_at__lt=moment).order_by('-digested_at').only('digest_order').first()
    return row.digest_order if row else 0


def get_event_sparkline_indexscan(start, end, interval, **filters):
    qs_base = Event.objects.filter(**filters)

    bucket_edges = []
    curr = start
    while curr <= end:
        bucket_edges.append(curr)
        curr += interval

    digest_orders = [
        _last_digest_order_before(edge, qs_base)
        for edge in bucket_edges
    ]

    buckets = []
    for i in range(1, len(bucket_edges)):
        count = digest_orders[i] - digest_orders[i - 1]
        buckets.append({'bucket_start': bucket_edges[i - 1], 'count': count})

    return buckets


def get_x_labels(start, end, num_labels=5):
    total_seconds = (end - start).total_seconds()
    step_seconds = total_seconds / (num_labels - 1)

    labels = []
    for i in range(num_labels):
        label_time = start + i * (end - start) / (num_labels - 1)
        labels.append(label_time)

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
