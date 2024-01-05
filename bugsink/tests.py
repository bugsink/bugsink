from datetime import datetime, timezone

from unittest import TestCase

from bugsink.period_counter import PeriodCounter, _prev_tup


def apply_n(f, n, v):
    for i in range(n):
        v = f(v)
    return v


class callback(object):
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


class PeriodCounterTestCase(TestCase):

    def test_prev_tup_near_rollover(self):
        self.assertEquals((2020,), _prev_tup((2021,)))

        self.assertEquals((2020,  1), _prev_tup((2020,  2)))
        self.assertEquals((2019, 12), _prev_tup((2020,  1)))

        self.assertEquals((2020,  1,  1), _prev_tup((2020,  1,  2)))
        self.assertEquals((2019, 12, 31), _prev_tup((2020,  1,  1)))
        self.assertEquals((2020,  2, 29), _prev_tup((2020,  3,  1)))
        self.assertEquals((2019,  2, 28), _prev_tup((2019,  3,  1)))

        self.assertEquals((2020,  1,  1, 10), _prev_tup((2020,  1,  1, 11)))
        self.assertEquals((2020,  1,  1,  0), _prev_tup((2020,  1,  1,  1)))
        self.assertEquals((2019, 12, 31, 23), _prev_tup((2020,  1,  1,  0)))
        self.assertEquals((2019, 12, 31, 22), _prev_tup((2019, 12, 31, 23)))

        self.assertEquals((2020,  1,  1,  0,  0), _prev_tup((2020,  1,  1,  0,  1)))
        self.assertEquals((2019, 12, 31, 23, 59), _prev_tup((2020,  1,  1,  0,  0)))

    def test_prev_tup_large_number_of_applications(self):
        self.assertEquals((1920,), apply_n(_prev_tup, 100, (2020,)))
        self.assertEquals((2010, 5), apply_n(_prev_tup, 120, (2020, 5)))
        self.assertEquals((2019, 5, 7,), apply_n(_prev_tup, 366, (2020, 5, 7)))
        self.assertEquals((2020, 5, 6, 20,), apply_n(_prev_tup, 24, (2020, 5, 7, 20,)))
        self.assertEquals((2020, 5, 6, 20, 12), apply_n(_prev_tup, 1440, (2020, 5, 7, 20, 12)))

    def test_prev_tup_with_explicit_n(self):
        self.assertEquals(_prev_tup((2020,), 100), apply_n(_prev_tup, 100, (2020,)))
        self.assertEquals(_prev_tup((2020, 5), 120), apply_n(_prev_tup, 120, (2020, 5)))
        self.assertEquals(_prev_tup((2020, 5, 7), 366), apply_n(_prev_tup, 366, (2020, 5, 7)))
        self.assertEquals(_prev_tup((2020, 5, 7, 20,), 24), apply_n(_prev_tup, 24, (2020, 5, 7, 20,)))
        self.assertEquals(_prev_tup((2020, 5, 7, 20, 12), 1440), apply_n(_prev_tup, 1440, (2020, 5, 7, 20, 12)))

    def test_prev_tup_works_for_empty_tup(self):
        # in general 'prev' is not defined for empty tuples; but it is convienient to define it as the empty tuple
        # because it makes the implementation of PeriodCounter simpler for the case of "all 1 'total' periods".

        self.assertEquals((), _prev_tup(()))
        # the meaninglessness of prev_tup is not extended to the case of n > 1, because "2 total periods" makes no sense
        # self.assertEquals((), _prev_tup((), 2))

    def test_foo(self):
        datetime_utc = datetime.now(timezone.utc)  # basically I just want to write this down somewhere
        pc = PeriodCounter()
        pc.inc(datetime_utc)

    def test_event_listeners_for_total(self):
        timepoint = datetime(2020, 1, 1, 10, 15, tzinfo=timezone.utc)

        pc = PeriodCounter()
        wbt = callback()
        wbf = callback()
        pc.add_event_listener("total", 1, 2, wbt, wbf, initial_event_state=False)

        # first inc: should not yet trigger
        pc.inc(timepoint)
        self.assertEquals(0, wbt.calls)

        # second inc: should trigger (threshold of 2)
        pc.inc(timepoint)
        self.assertEquals(1, wbt.calls)

        # third inc: should not trigger again
        pc.inc(timepoint)
        self.assertEquals(1, wbt.calls)

    def test_event_listeners_for_year(self):
        tp_2020 = datetime(2020, 1, 1, 10, 15, tzinfo=timezone.utc)
        tp_2021 = datetime(2021, 1, 1, 10, 15, tzinfo=timezone.utc)
        tp_2022 = datetime(2022, 1, 1, 10, 15, tzinfo=timezone.utc)

        pc = PeriodCounter()
        wbt = callback()
        wbf = callback()
        pc.add_event_listener("year", 2, 3, wbt, wbf, initial_event_state=False)

        pc.inc(tp_2020)
        self.assertEquals(0, wbt.calls)

        pc.inc(tp_2020)
        self.assertEquals(0, wbt.calls)

        # 3rd in total: become True
        pc.inc(tp_2021)
        self.assertEquals(1, wbt.calls)

        # into a new year, total == 2: become false
        self.assertEquals(0, wbf.calls)
        pc.inc(tp_2022)
        self.assertEquals(1, wbf.calls)
        self.assertEquals(1, wbt.calls)  # unchanged

        # 3rd in (new) total: become True again
        pc.inc(tp_2022)
        self.assertEquals(2, wbt.calls)
        self.assertEquals(1, wbf.calls)  # unchanged
