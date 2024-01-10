from collections import namedtuple
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


EventListener = namedtuple("EventListener", "when_becomes_true when_becomes_false purpose is_true")


def change_state(listener, is_true):
    return EventListener(
        when_becomes_true=listener.when_becomes_true,
        when_becomes_false=listener.when_becomes_false,
        purpose=listener.purpose,
        is_true=is_true,
    )


def noop():
    pass


def _prev_tup(tup, n=1):
    aslist = list(tup)

    # if n > 1 we try to first remove the largest possible chunk from the last element of the tuple, so that we can
    # then do the remainder in the loop (for performance reasons)
    if n > 1:
        DONE_IN_LOOP = 1
        first_chunk = min(n - DONE_IN_LOOP, max(0, tup[-1] - MIN_VALUE_AT_TUP_INDEX[-1] - DONE_IN_LOOP))
        aslist[-1] -= first_chunk
        remainder = n - first_chunk - DONE_IN_LOOP
    else:
        remainder = 0

    for tup_index, val in reversed(list(enumerate(aslist))):
        if aslist[tup_index] == MIN_VALUE_AT_TUP_INDEX[tup_index]:
            if tup_index == 2:
                # day roll-over: just use a datetime
                aslist = list((datetime(*aslist, tzinfo=timezone.utc) - timedelta(days=1)).timetuple()[:len(tup)])
                break  # we've used a timedelta, so we don't need to do months/years "by hand" in the loop

            else:
                # roll over to max
                aslist[tup_index] = MAX_VALUE_AT_TUP_INDEX[tup_index]
                # implied because no break: continue with the left hand side of the tuple

        else:
            aslist[tup_index] -= 1
            break

    if remainder > 0:
        return _prev_tup(aslist, remainder)

    return tuple(aslist)


def _inc(counts_for_tl, tup, n, max_age):
    is_new_period = False

    if tup not in counts_for_tl:
        is_new_period = True
        min_tup = _prev_tup(tup, max_age - 1)
        for k, v in list(counts_for_tl.items()):
            if k < min_tup:
                del counts_for_tl[k]

        # default
        counts_for_tl[tup] = 0

    # inc
    counts_for_tl[tup] += n
    return is_new_period


class PeriodCounter(object):

    def __init__(self):
        self.counts = {tuple_length: {} for tuple_length in range(TL_MINUTE + 1)}
        self.event_listeners = {tuple_length: {} for tuple_length in range(TL_MINUTE + 1)}

    def inc(self, datetime_utc, n=1):
        # we only allow UTC, and we generally use Django model fields, which are UTC, so this should be good:
        assert datetime_utc.tzinfo == timezone.utc

        tup = datetime_utc.timetuple()

        for tl, mx in enumerate([MAX_TOTALS, MAX_YEARS, MAX_MONTHS, MAX_DAYS, MAX_HOURS, MAX_MINUTES]):
            is_new_period = _inc(self.counts[tl], tup[:tl], n, mx)

            event_listeners_for_tl = self.event_listeners[tl]
            for ((nr_of_periods, gte_threshold), listener) in list(event_listeners_for_tl.items()):
                if listener.is_true:
                    if not is_new_period:
                        continue  # no new period means: never becomes false, because no old period becomes irrelevant

                    if not self._get_event_state(tup[:tl], tl, nr_of_periods, gte_threshold):
                        event_listeners_for_tl[(nr_of_periods, gte_threshold)] = change_state(listener, False)
                        listener.when_becomes_false()

                else:
                    if self._get_event_state(tup[:tl], tl, nr_of_periods, gte_threshold):
                        event_listeners_for_tl[(nr_of_periods, gte_threshold)] = change_state(listener, True)
                        listener.when_becomes_true()

    def add_event_listener(self, period_name, nr_of_periods, gte_threshold, when_becomes_true=noop,
                           when_becomes_false=noop, purpose=None, initial_event_state=None, tup=None):
        # NOTE as it stands we store only a single event_listener at the key (nr_of_periods, gte_threshold); this means
        # that if you add a second event_listener with the same key, it will overwrite the first one. As long as we have
        # a single event-listener per goal (e.g. unmuting) this may actually be a feature; but if we start monitoring
        # both quota/unmuting in a single period_counter, these things will conflict and we'll need to keep a list as
        # the values in our dict.

        # note: the 'events' here are not bugsink-events; but the more general concept of 'an event'; we may consider a
        # different name for this in the future because of that.

        # tup means: tup for the current time, which can be used to determine the initial state of the event listener.

        if len([arg for arg in [initial_event_state, tup] if arg is None]) != 1:
            # either be explicit, or let us deduce
            raise ValueError("Provide exactly one of (initial_event_state, tup)")

        tl = self._tl_for_period(period_name)
        if initial_event_state is None:
            initial_event_state = self._get_event_state(tup[:tl], tl, nr_of_periods, gte_threshold)

        self.event_listeners[tl][(nr_of_periods, gte_threshold)] = \
            EventListener(when_becomes_true, when_becomes_false, purpose, initial_event_state)

    def remove_event_listener(self, purpose):
        """
        Remove all event listeners with the given purpose. The purpose is a string that can be used to identify the
        event listener. (The idea is: callbacks are organized by purpose, and when you want to remove a callback, you
        can do so by specifying the purpose.)
        """
        for tl, mx in enumerate([MAX_TOTALS, MAX_YEARS, MAX_MONTHS, MAX_DAYS, MAX_HOURS, MAX_MINUTES]):
            for k, (wbt, wbf, this_purp, state) in list(self.event_listeners[tl].items()):
                if this_purp == purpose:
                    del self.event_listeners[tl][k]

    def _tl_for_period(self, period_name):
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
