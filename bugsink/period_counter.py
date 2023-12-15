from datetime import datetime, timezone, timedelta

# these constants are quite arbitrary; it can easily be argued that 90 minutes is an interesting time-frame (because of
# the loss of granularity when stepping up to minutes) but we pick something that's close to the next level of
# granularity. We can start measuring performance (time, memory) from there and can always make it bigger later.

MAX_MINUTES = 60
MAX_HOURS = 24
MAX_DAYS = 30
MAX_MONTHS = 12
MAX_YEARS = 5


FOO_MIN = 1000, 1, 1, 0, 0
FOO_MAX = 3000, 12, "?", 23, 59


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
    if tup not in d:
        # evict
        min_tup = apply_n(_prev_tup, max_age, tup)
        d = {k: v for k, v in d.items() if d >= min_tup}

        # default
        d[tup] = 0

    # inc
    d[tup] += n


class PeriodCounter(object):

    def __init__(self):
        self.total = 0
        self.years = {}
        self.months = {}
        self.days = {}
        self.hours = {}
        self.minutes = {}

    def inc(self, datetime_utc, n=1):
        tup = datetime_utc.timetuple()

        self.total += n   # self.forevers, ()

        _inc(self.years,   tup[:1], n, MAX_YEARS)
        _inc(self.months,  tup[:2], n, MAX_MONTHS)
        _inc(self.days,    tup[:3], n, MAX_DAYS)
        _inc(self.hours,   tup[:4], n, MAX_HOURS)
        _inc(self.minutes, tup[:5], n, MAX_MINUTES)
