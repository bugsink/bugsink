from datetime import datetime, timezone, timedelta

# these constants are quite arbitrary; it can easily be argued that 90 minutes is an interesting time-frame (because of
# the loss of granularity when stepping up to minutes) but we pick something that's close to the next level of
# granularity. We can start measuring performance (time, memory) from there and can always make it bigger later.

# i.e. keep 60 minutes of 60 seconds each, 24 hours of 3600 seconds each etc.
MAX_MINUTES = 60 * 60
MAX_HOURS = 24 * (60 * 60)
MAX_DAYS = 30 * (60 * 60 * 24)
MAX_MONTHS = 366 * (60 * 60 * 24)  # i.e. 12 months will be available
MAX_YEARS = 5 * (366 * 60 * 60 * 24)


def _inc(d, tup, n, max_age):
    if tup not in d:
        # evict
        min_tup = (datetime(*tup, tzinfo=timezone.utc) - timedelta(max_age)).timetuple()[:len(tup)]
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
