from datetime import datetime, timezone

from unittest import TestCase

from bugsink.period_counter import PeriodCounter


class PeriodCounterTestCase(TestCase):

    def test_foo(self):
        datetime_utc = datetime.now(timezone.utc)  # basically I just want to write this down somewhere
        pc = PeriodCounter()
        pc.inc(datetime_utc)
