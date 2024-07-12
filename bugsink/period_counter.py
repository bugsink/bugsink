from datetime import datetime, timezone, timedelta

# these constants are quite arbitrary; it can easily be argued that 90 minutes is an interesting time-frame (because of
# the loss of granularity when stepping up to minutes) but we pick something that's close to the next level of
# granularity. We can start measuring performance (time, memory) from there and can always make it bigger later.

MAX_MINUTES = 60
MAX_HOURS = 24
MAX_DAYS = 30
MAX_MONTHS = 12
MAX_YEARS = 5
MAX_TOTALS = 1


MIN_VALUE_AT_TUP_INDEX = 1000, 1, 1, 0, 0
MAX_VALUE_AT_TUP_INDEX = 3000, 12, "?", 23, 59


# TL for "tuple length", the length of the tuples for a given time-period
TL_TOTAL = 0
TL_YEAR = 1
TL_MONTH = 2
TL_DAY = 3
TL_HOUR = 4
TL_MINUTE = 5


def noop():
    pass


def _prev_tup(tup, n=1):
    aslist = list(tup)

    # if n > 1 we try to first remove the largest possible chunk from the last element of the tuple (for performance
    # reasons), so that we can then do the remainder in the loop (always 1) and the recursive call (the rest)
    if n > 1:
        DONE_IN_LOOP = 1
        first_chunk = max(min(  # the minimum of:
            n - DONE_IN_LOOP,  # [A] the work to be done minus 1 in the loop-over-digits below
            tup[-1] - MIN_VALUE_AT_TUP_INDEX[len(tup) - 1],  # [B] jump to roll-over right before entering that loop
            ), 0)  # but never less than 0
        aslist[-1] -= first_chunk
        n_for_recursive_call = n - first_chunk - DONE_IN_LOOP
    else:
        n_for_recursive_call = 0

    # In this loop we just decrease by 1;
    for tup_index, val in reversed(list(enumerate(aslist))):
        # we inspect the parts of the tuple right-to-left and continue to decrease until there is no more roll-over.

        if aslist[tup_index] == MIN_VALUE_AT_TUP_INDEX[tup_index]:
            # we've reached the min value which is the case that influences more than the current digit.
            if tup_index == 2:
                # day roll-over: just use a datetime because the max value is one of 28, 29, 30, 31.
                aslist = list((datetime(*aslist, tzinfo=timezone.utc) - timedelta(days=1)).timetuple()[:len(tup)])
                break  # we've used a timedelta, so we don't need to do months/years "by hand" in the loop

            else:
                # roll over to max
                aslist[tup_index] = MAX_VALUE_AT_TUP_INDEX[tup_index]
                # implied because no break: continue with the next more significant digit of the tuple

        else:
            # no min-value reached, just dec at this point and stop.
            aslist[tup_index] -= 1
            break

    if n_for_recursive_call > 0:
        return _prev_tup(aslist, n_for_recursive_call)

    return tuple(aslist)


def _inc(counts_for_tl, tup, n, max_age):
    if tup not in counts_for_tl:
        min_tup = _prev_tup(tup, max_age - 1)
        for k, v in list(counts_for_tl.items()):
            if k < min_tup:
                del counts_for_tl[k]

        # default
        counts_for_tl[tup] = 0

    # inc
    counts_for_tl[tup] += n


def _reorganize_by_tl(thresholds_by_purpose):
    by_tl = {}

    for purpose, items in thresholds_by_purpose.items():
        for (period_name, nr_of_periods, gte_threshold, metadata) in items:
            tl = PeriodCounter._tl_for_period(period_name)

            if tl not in by_tl:
                by_tl[tl] = []

            by_tl[tl].append((nr_of_periods, gte_threshold, metadata, purpose))

    return by_tl


class PeriodCounter(object):

    def __init__(self):
        self.counts = {tuple_length: {} for tuple_length in range(TL_MINUTE + 1)}

    def inc(self, datetime_utc, n=1, thresholds={}):
        # thresholds :: purpose -> [(period_name, nr_of_periods, gte_threshold, metadata), ...]

        # we only allow UTC, and we generally use Django model fields, which are UTC, so this should be good:
        assert datetime_utc.tzinfo == timezone.utc

        tup = datetime_utc.timetuple()

        thresholds_by_tl = _reorganize_by_tl(thresholds)
        states_with_metadata_by_purpose = {purpose: [] for purpose in thresholds.keys()}

        for tl, mx in enumerate([MAX_TOTALS, MAX_YEARS, MAX_MONTHS, MAX_DAYS, MAX_HOURS, MAX_MINUTES]):
            _inc(self.counts[tl], tup[:tl], n, mx)

            thresholds_for_tl = thresholds_by_tl.get(tl, {})
            for (nr_of_periods, gte_threshold, metadata, purpose) in thresholds_for_tl:
                state = self._get_event_state(tup[:tl], tl, nr_of_periods, gte_threshold)
                states_with_metadata_by_purpose[purpose].append((state, metadata))

        # we return tuples of (state, metadata) where metadata is something arbitrary that can be passed in (it allows
        # us to tie back to "what caused this to be true/false?"
        return states_with_metadata_by_purpose

    @staticmethod
    def _tl_for_period(period_name):
        return {
            "total": 0,
            "year": 1,
            "month": 2,
            "day": 3,
            "hour": 4,
            "minute": 5,
        }[period_name]

    def _get_event_state(self, tup, tl, nr_of_periods, gte_threshold):
        min_tup = _prev_tup(tup, nr_of_periods - 1) if tup != () else ()
        counts_for_tl = self.counts[tl]
        total = sum([v for k, v in counts_for_tl.items() if k >= min_tup])

        return total >= gte_threshold
