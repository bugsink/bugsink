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
    # TODO: isn't this a premature optimization? We could just use a datetime/timedelta?
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


def _next_tup(tup, n=1):
    aslist = list(tup)

    # no 'first_chunk' implementation here, calls to _next_tup() are not a hot path in our code anyway.

    for i in range(n):
        # In this loop we just increase by 1;
        for tup_index, val in reversed(list(enumerate(aslist))):
            # we inspect the parts of the tuple right-to-left and continue to decrease until there is no more roll-over.

            if (tup_index == 2 and aslist[tup_index] >= 28) or aslist[tup_index] == MAX_VALUE_AT_TUP_INDEX[tup_index]:
                # we've reached the min value which is the case that influences more than the current digit.
                if tup_index == 2:
                    # day roll-over (potentially, 28 and up): just use a datetime (the max value is one of 28, 29, 30,
                    # 31)
                    aslist = list((datetime(*aslist, tzinfo=timezone.utc) + timedelta(days=1)).timetuple()[:len(tup)])
                    break  # we've used a timedelta, so we don't need to do months/years "by hand" in the loop

                else:
                    # roll over to min
                    aslist[tup_index] = MIN_VALUE_AT_TUP_INDEX[tup_index]
                    # implied because no break: continue with the next more significant digit of the tuple

            else:
                # no min-value reached, just inc at this point and stop.
                aslist[tup_index] += 1
                break

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
                state = self._state_for_threshold(tup[:tl], tl, nr_of_periods, gte_threshold)
                if state:
                    if tl > 0:
                        # `below_threshold_from` is the first moment in time where the condition no longer applies.
                        below_threshold_tup = _next_tup(
                            self._get_first_tup_contributing_to_threshold(tup[:tl], tl, nr_of_periods),

                            # +1 for "next period" (the first where the condition no longer applies), -1 for "first
                            # period counts" hence no +/- correction.
                            n=nr_of_periods,
                        ) + MIN_VALUE_AT_TUP_INDEX[tl:]  # fill with min values for the non-given ones
                        below_threshold_from = datetime(*below_threshold_tup, tzinfo=timezone.utc)
                    else:
                        # when counting the 'total', there will never be a time when the condition becomes false. We
                        # just pick an arbitrarily large date; we'll deal with it by the end of the myria-annum.
                        # unlikely to actually end up in the DB (because it would imply the use of a quota for total).
                        below_threshold_from = datetime(9999, 12, 31, 23, 59, tzinfo=timezone.utc)
                else:
                    below_threshold_from = None

                states_with_metadata_by_purpose[purpose].append((state, below_threshold_from, metadata))

        # we return tuples of (state, below_threshold_from, metadata) where metadata is something arbitrary that can be
        # passed in (it allows us to tie back to "what caused this to be true/false?"
        # TODO: I think that in practice the metadata is always implied by the thresholds, i.e. instead of
        # passing-through we could just return the thresholds that were met.
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

    def _state_for_threshold(self, tup, tl, nr_of_periods, gte_threshold):
        min_tup = _prev_tup(tup, nr_of_periods - 1) if tup != () else ()  # -1 because the current one also counts
        counts_for_tl = self.counts[tl]
        total = sum([v for k, v in counts_for_tl.items() if k >= min_tup])

        return total >= gte_threshold

    def _get_first_tup_contributing_to_threshold(self, tup, tl, nr_of_periods):
        # there's code duplication here with _state_for_threshold which also results in stuff being executed twice when
        # the state is True; however, getting rid of this would be a "premature optimization", because states "flip to
        # true" only very irregularly (for unmute flip-to-true results in removal from the 'watch list', and for quota
        # flip-to-true results in 'no more ingestion for a while')
        min_tup = _prev_tup(tup, nr_of_periods - 1) if tup != () else ()
        counts_for_tl = self.counts[tl]
        return min([k for k, v in counts_for_tl.items() if k >= min_tup and v > 0])
