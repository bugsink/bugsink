from datetime import datetime, timezone

from unittest import TestCase

from bugsink.period_counter import PeriodCounter, _prev_tup


def apply_n(f, n, v):
    for i in range(n):
        v = f(v)
    return v


class PeriodCounterTestCase(TestCase):

    def test_prev_tup(self):
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

        self.assertEquals((1920,), apply_n(_prev_tup, 100, (2020,)))
        self.assertEquals((2010, 5), apply_n(_prev_tup, 120, (2020, 5)))
        self.assertEquals((2019, 5, 7,), apply_n(_prev_tup, 366, (2020, 5, 7)))
        self.assertEquals((2020, 5, 6, 20,), apply_n(_prev_tup, 24, (2020, 5, 7, 20,)))
        self.assertEquals((2020, 5, 6, 20, 12), apply_n(_prev_tup, 1440, (2020, 5, 7, 20, 12)))

    def test_foo(self):
        datetime_utc = datetime.now(timezone.utc)  # basically I just want to write this down somewhere
        pc = PeriodCounter()
        pc.inc(datetime_utc)
