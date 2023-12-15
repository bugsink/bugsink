from datetime import datetime, timezone

from unittest import TestCase

from bugsink.period_counter import PeriodCounter, _prev_tup


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

    def test_foo(self):
        datetime_utc = datetime.now(timezone.utc)  # basically I just want to write this down somewhere
        pc = PeriodCounter()
        pc.inc(datetime_utc)
