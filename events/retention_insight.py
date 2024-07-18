from datetime import datetime, timezone

from .retention import get_epoch_bounds_with_irrelevance, get_irrelevance_pairs, datetime_for_epoch
from .models import Event


def retention_insight_values(project):
    timestamp = datetime.now(tz=timezone.utc)

    # we call with qs_kwargs={} here, because we want to see what actually exists including any never_evict=True events.
    # (the default (used during actual eviction) is to ignore such events when creating bounds and pairs, because they
    # cannot be deleted anyway)
    epoch_bounds_with_irrelevance = get_epoch_bounds_with_irrelevance(project, timestamp, qs_kwargs={})
    pairs = list(get_irrelevance_pairs(project, epoch_bounds_with_irrelevance, qs_kwargs={}))

    yielded = 0
    for (age_based_irrelevance, max_obsered_irrelevance), ((lb, ub), _) in reversed(list(zip(pairs, epoch_bounds_with_irrelevance))):
        print("?", age_based_irrelevance, max_obsered_irrelevance, lb, ub)
        results = {}
        for irrelevance in range(max_obsered_irrelevance + 1):
            qs = Event.objects.filter(
                project=project,
                irrelevance_for_retention=irrelevance
            )
            if lb is not None:
                qs = qs.filter(digested_at__gte=datetime_for_epoch(lb))
            if ub is not None:
                qs = qs.filter(digested_at__lt=datetime_for_epoch(ub))

            howmany = qs.count()
            results[irrelevance] = howmany
            yielded += howmany

        yield (lb, results)  # lb makes more sense visually

    assert Event.objects.filter(project=project).count() == yielded, "%d != %d" % (Event.objects.filter(project=project).count(), yielded)


def retention_insight(project):
    data = list(retention_insight_values(project))
    print(data)

    max_irrelevance = max(max(d.keys() for _, d in data), default=0)
    # max_count = max(max(d.values() for _, d in data), default=0)  idea: use for formatting, but dates are bigger

    # len("2000-01-01 16h") == 14 -> 16 for padding
    fmt = lambda epoch: datetime_for_epoch(epoch).strftime("%Y-%m-%d %Hh  ") if epoch is not None else " " * 16  # noqa

    # headers
    print(" " * 5, end="")
    for epoch, _ in data:
        print(fmt(epoch), end="")
    print()

    for irrelevance in range(max_irrelevance + 1):
        print("%3d| " % irrelevance, end="")
        for epoch, results in data:
            if results.get(irrelevance, 0) == 0:
                print(" " * 13 + ".  ", end="")
            else:
                print("%14d  " % results.get(irrelevance, 0), end="")
        print()

    print("Total: ", sum(sum(d.values()) for _, d in data))
