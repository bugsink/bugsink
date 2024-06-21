from django.db.models import Q, Min, Max

from random import random
from datetime import timezone, datetime


def get_epoch(datetime_obj):
    # the basic rythm for eviction is 'hourly'; we define an 'epoch' for eviction as the number of hours since 1970.

    # assuming we use model fields this 'just works' because Django's stores its stuff in timezone-aware UTC in the DB.
    assert datetime_obj.tzinfo == timezone.utc

    return int(datetime_obj.timestamp() / 3600)


def datetime_for_epoch(epoch):
    return datetime.fromtimestamp(epoch * 3600, timezone.utc)


def get_epoch_bounds(lower, upper=None):
    if lower is None and upper is None:
        return Q()

    if lower is None:
        return Q(timestamp__lt=datetime_for_epoch(upper))

    if upper is None:
        return Q(timestamp__gte=datetime_for_epoch(lower))

    return Q(timestamp__gte=datetime_for_epoch(lower), timestamp__lt=datetime_for_epoch(upper))


def nonzero_leading_bits(n):
    """
    Return the non-roundness of a number when represented in binary, i.e. the number of leading bits until the last 1.
    examples:

    100000 -> 1
    101000 -> 3
    110001 -> 6
    """
    s = format(n, 'b')
    return len(s.rstrip('0'))


def get_random_irrelevance(event_count):
    """
    gets a fixed-at-creation irrelevance-score for an Event; the basic idea is: the more events you have for a certain
    issue, the less relevant any new event will be _on average_; but when you have many events you will on average still
    have more relevant events than if you have few events.

    irrelevance is basically determined by `nonzero_leading_bits`; we add some randomization to avoid repeated outcomes
    if `cnt` "hovers" around a certain value (which is likely to happen when there's repeated eviction/fill-up). ×2 is
    simply to correct for random() (which returns .5 on average).
    """
    return nonzero_leading_bits(round(random() * event_count * 2))


def should_evict(project, timestamp, stored_event_count):
    # if/when we implement 'just drop' this might go somewhere (maybe not here)
    # if (project.retention_last_eviction is not None and
    #         get_epoch(project.retention_last_eviction) != get_epoch(timestamp)):
    #     return True

    if stored_event_count > project.retention_max_event_count:  # > because: do something when _over_ the max
        return True

    return False


def get_age_for_irrelevance(age_based_irrelevance):
    #
    # age based irrelevance is defined as `log(age + 1, 2)`
    #
    # (This is what we chose because we want 0-aged to have an age-based irrelevance of 0); i.e. that's where the +1
    # comes from.
    #
    # at the integer values for irrelevance this works out like so:
    # age = 0 => irrelevance = 0
    # age = 1 => irrelevance = 1
    # age = 2 => irrelevance = 1.58
    # age = 3 => irrelevance = 2
    # ...
    # age = 7 => irrelevance = 3
    #
    # to work back from a given integer "budget" of irrelevance (after the (integer) item-based irrelevance has been
    # subtracted from the total max), we can simply take `2^budget - 1` to get the 'age of eviction', the number of
    # epochs we must go back. The following code helps me understand this:
    #
    # >>> for budget in range(8):
    # ...     age = pow(2, budget) - 1
    # ...     print("budget: %s, age: %s" % (budget, age))

    return pow(2, age_based_irrelevance) - 1


def get_epoch_bounds_with_irrelevance(project, current_timestamp):
    from .models import Event

    # TODO 'first_seen' is cheaper? I don't think it exists at project-level though.
    # We can safely assume some Event exists when this point is reached because of the conditions in `should_evict`
    first_epoch = get_epoch(Event.objects.filter(project=project).aggregate(val=Min('server_side_timestamp'))['val'])
    current_epoch = get_epoch(current_timestamp)

    difference = current_epoch - first_epoch

    # because we construct in reverse order (from the most recent to the oldest) we end up with the pairs swapped
    swapped_bounds = pairwise(
        [None] + [current_epoch - n for n in list(map_N_until(get_age_for_irrelevance, difference))] + [None])

    return [((lb, ub), age_based_irrelevance) for age_based_irrelevance, (ub, lb) in enumerate(swapped_bounds)]


def get_irrelevance_pairs(project, epoch_bounds_with_irrelevance):
    """tuples of `age_based_irrelevance` and, per associated period, the max observed event irrelevance"""
    from .models import Event

    for (lower_bound, upper_bound), age_based_irrelevance in epoch_bounds_with_irrelevance:
        d = Event.objects.filter(get_epoch_bounds(lower_bound, upper_bound)).aggregate(Max('irrelevance_for_retention'))
        max_event_irrelevance = d["irrelevance_for_retention__max"] or 0

        yield (age_based_irrelevance, max_event_irrelevance)


def map_N_until(f, until, onemore=False):
    n = 0
    result = f(n)
    while result < until:
        yield result
        n += 1
        result = f(n)
    if onemore:
        yield result


def pairwise(it):
    it = iter(it)
    try:
        prev = next(it)
    except StopIteration:
        return
    for current in it:
        yield (prev, current)
        prev = current


def filter_for_work(epoch_bounds_with_irrelevance, pairs, max_total_irrelevance):
    # Here, we filter out epoch bounds for which there is obviously no work to be done, based on the pairs that we have
    # selected at the beginning of the algo. We compare the selected irrelevances with the total, and if they do not
    # exceed it no work will need to be done for that set of epochs.

    # Since it uses only the (already available) information that was gathered at the beginning of the algo, it is not a
    # full filter for avoiding useless deletions, but at least we use the available info (from queries) to the fullest.
    for pair, ebwi in zip(pairs, epoch_bounds_with_irrelevance):
        if sum(pair) > max_total_irrelevance:  # > because only if it is strictly greater will anything be evicted.
            yield ebwi


def evict_for_max_events(project, timestamp, stored_event_count=None):
    from .models import Event

    if stored_event_count is None:
        # allowed as a pass-in to save a query (we generally start off knowing this)
        stored_event_count = Event.objects.filter(project=project).count() + 1

    epoch_bounds_with_irrelevance = get_epoch_bounds_with_irrelevance(project, timestamp)

    # we start off with the currently observed max total irrelevance
    pairs = get_irrelevance_pairs(project, epoch_bounds_with_irrelevance)
    max_total_irrelevance = max(sum(pair) for pair in pairs)

    while stored_event_count > project.retention_max_event_count:  # > as in `should_evict`
        # -1 at the beginning of the loop; this means the actually observed max value is precisely the first thing that
        # will be evicted (since `evict_for_irrelevance` will evict anything above (but not including) the given value)
        max_total_irrelevance -= 1

        evict_for_irrelevance(max_total_irrelevance, epoch_bounds_with_irrelevance)

        stored_event_count = Event.objects.filter(project=project).count()

        if max_total_irrelevance < -1:  # < -1: see test below for why.
            # could still happen ('in theory') if there's max_size items of irrelevance 0 (in the real impl. we'll have
            # to separately deal with that, i.e. evict-and-warn) TODO
            raise Exception("No more effective eviction possible but target not reached")

    # print("Evicted down to %d with a max_total_irrelevance of %d" % (observed_size, max_total_irrelevance)) TODO log
    return max_total_irrelevance


def evict_for_irrelevance(max_total_irrelevance, epoch_bounds_with_irrelevance):
    # print("evict_for_irrelevance(%d, %s)" % (max_total_irrelevance, epoch_bounds_with_irrelevance))

    # max_total_irrelevance, i.e. the total may not exceed this (but it may equal it)

    for (_, epoch_ub_exclusive), irrelevance_for_age in epoch_bounds_with_irrelevance:
        max_item_irrelevance = max_total_irrelevance - irrelevance_for_age

        evict_for_epoch_and_irrelevance(epoch_ub_exclusive, max_item_irrelevance)

        if max_item_irrelevance <= -1:
            # in the actual eviction, the test on max_item_irrelevance is done exclusively, i.e. only items of greater
            # irrelevance are evicted. The minimal actually occuring value is 0. Such items can be evicted with a call
            # with max_item_irrelevance = -1. This means that if we just did such an eviction, we're done for all epochs
            break


def evict_for_epoch_and_irrelevance(max_epoch, max_irrelevance):
    # print("evict_for_epoch_and_irrelevance(%s, %s)" % (max_epoch, max_irrelevance))

    from .models import Event
    # evicting "at", based on the total irrelevance split out into 2 parts: max item irrelevance, and an epoch as
    # implied by the age-based irrelevance.

    # (both max_epoch and max_irrelevance are _exclusive_)

    # Note: we simply use a single age-based UB-check to delete; an alternative is to also use associated time-based-LB
    # for a given `irrelevance_for_age`; in practice it doesn't matter, because in the same `evict_for_irrelevance` call
    # the older epochs will be visited later with an even lower value for `max_irrelevance` which would delete the same.
    # But we might use this fact at some point in the future (e.g. for performance considerations, or to evict in
    # smaller steps).
    #
    # As a picture (time on X, irrelevance on the Y axis, lower rows have higher irrelevance as in the simulation):
    #
    #  . . . . . . .
    #          B B .
    #  a a a a x x A
    #
    # As implemented, we evict the points marked `A`, `x` and `a` all in a single go. The alternative would be: `A` in
    # this call, and only when `B` is cleaned will the points `x` be cleaned. (as-is, they are part of the selection,
    # but will already have been deleted)

    qs = Event.objects.filter(irrelevance_for_retention__gt=max_irrelevance)

    if max_epoch is not None:
        qs = qs.filter(server_side_timestamp__lt=datetime_for_epoch(max_epoch))

    qs.delete()
