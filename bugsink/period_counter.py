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


FOO_MIN = 1000, 1, 1, 0, 0
FOO_MAX = 3000, 12, "?", 23, 59


# TL for "tuple length", the length of the tuples for a given time-period
TL_TOTAL = 0
TL_YEAR = 1
TL_MONTH = 2
TL_DAY = 3
TL_HOUR = 4
TL_MINUTE = 5


def apply_n(f, n, v):
    for i in range(n):
        v = f(v)
    return v


def _prev_tup(tup):
    aslist = list(tup)
    for i, val in reversed(list(enumerate(aslist))):
        if aslist[i] == FOO_MIN[i]:
            if i == 2:
                # day roll-over: just use a datetime
                aslist = list((datetime(*aslist, tzinfo=timezone.utc) - timedelta(days=1)).timetuple()[:len(tup)])
                break

            else:
                # roll over to max
                aslist[i] = FOO_MAX[i]
                # implied because no break: continue with the left hand side

        else:
            aslist[i] -= 1
            break

    return tuple(aslist)


def _inc(d, tup, n, max_age):
    new_period = False

    if tup not in d:
        if len(d) > 0:
            new_period = True
            min_tup = apply_n(_prev_tup, max_age - 1, tup)
            for k, v in list(d.items()):
                if k < min_tup:
                    del d[k]

        # default
        d[tup] = 0

    # inc
    d[tup] += n
    return new_period


class PeriodCounter(object):

    def __init__(self):
        self.counts = {tuple_length: {} for tuple_length in range(TL_MINUTE + 1)}
        self.event_listeners = {tuple_length: {} for tuple_length in range(TL_MINUTE + 1)}

    def inc(self, datetime_utc, n=1):
        tup = datetime_utc.timetuple()

        for tl, mx in enumerate([MAX_TOTALS, MAX_YEARS, MAX_MONTHS, MAX_DAYS, MAX_HOURS, MAX_MINUTES]):
            new_period = _inc(self.counts[tl], tup[:tl],  n, mx)

            event_listeners_for_tl = self.event_listeners[tl]
            for ((how_many_periods, gte_threshold), (wbt, wbf, is_true)) in list(event_listeners_for_tl.items()):
                if is_true:
                    if not new_period:
                        continue  # no new period means: never becomes false, because no old period becomes irrelevant

                    if not self._get_event_state(tup[:tl], tl, how_many_periods, gte_threshold):
                        event_listeners_for_tl[(how_many_periods, gte_threshold)] = (wbt, wbf, False)
                        wbf()

                else:
                    if self._get_event_state(tup[:tl], tl, how_many_periods, gte_threshold):
                        event_listeners_for_tl[(how_many_periods, gte_threshold)] = (wbt, wbf, True)
                        wbt()

    def add_event_listener(self, period_name, how_many_periods, gte_threshold, when_becomes_true, when_becomes_false,
                           initial_event_state=None, tup=None):

        if len([arg for arg in [initial_event_state, tup] if arg is None]) != 1:
            # either be explicit, or let us deduce
            raise ValueError("Provide exactly one of (initial_event_state, tup)")

        tl = self._tl_for_period(period_name)
        if initial_event_state is None:
            initial_event_state = self._get_event_state(tup, tl, how_many_periods, gte_threshold)

        self.event_listeners[tl][(how_many_periods, gte_threshold)] = \
            (when_becomes_true, when_becomes_false, initial_event_state)

    def _tl_for_period(self, period_name):
        return {
            "total": 0,
            "year": 1,
            "month": 2,
            "day": 3,
            "hour": 4,
            "minute": 5,
        }[period_name]

    def _get_event_state(self, tup, tl, how_many_periods, gte_threshold):
        min_tup = apply_n(_prev_tup, how_many_periods - 1, tup)
        d = self.counts[tl]
        total = sum([v for k, v in d.items() if k >= min_tup])

        return total >= gte_threshold
