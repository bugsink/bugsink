import random
import time
from datetime import datetime, timezone

from bugsink.period_counter import _prev_tup, PeriodCounter

from performance.bursty_data import generate_bursty_data, buckets_to_points_in_time


# this file is the beginning of an approach to getting a handle on performance.


class passed_time(object):
    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, type, value, traceback):
        self.elapsed = (time.time() - self.t0) * 1_000  # miliseconds is a good unit for timeing things


def print_thoughts_about_prev_tup():
    v = (2020, 1, 1, 10, 10)
    with passed_time() as t:
        for i in range(1_000):
            v = _prev_tup(v)

    print(f"""## _prev_tup()

1_000 iterations of _prev_tup in {t.elapsed:.3f}ms. The main thing we care about is not this little
private helper though, but PeriodCounter.inc(). Let's test that next.

""")


def print_thoughts_about_inc():
    random.seed(42)

    pc = PeriodCounter()

    # make sure the pc has some data before we start
    for point in buckets_to_points_in_time(
        generate_bursty_data(num_buckets=350, expected_nr_of_bursts=10),
        datetime(2020, 10, 15, tzinfo=timezone.utc),
        datetime(2021, 10, 15, 10, 5, tzinfo=timezone.utc),
        10_000,
            ):

        pc.inc(point)

    points = buckets_to_points_in_time(
        generate_bursty_data(num_buckets=25, expected_nr_of_bursts=5),
        datetime(2021, 10, 15, 10, 5, tzinfo=timezone.utc),
        datetime(2021, 10, 16, 10, 5, tzinfo=timezone.utc),
        1000)

    with passed_time() as t:
        for point in points:
            pc.inc(point)

    print(f"""## PeriodCounter.inc()

1_000 iterations of PeriodCounter.inc() in {t.elapsed:.3f}ms. We care about evaluation of some event more though. Let's
test that next.
""")


def print_thoughts_about_event_evaluation():
    random.seed(42)

    pc = PeriodCounter()

    def noop():
        pass

    # Now, let's add some event-listeners. These are chosen to match a typical setup of quota for a given Issue or
    # Project. In this setup, the monthly maximum is spread out in a way that the smaller parts are a bit more than just
    # splitting things equally. Why? We want some flexibility for bursts of activity without using up the entire budget
    # for a longer time all at once.
    pc.add_event_listener("day",    30, 10_000, noop, noop, initial_event_state=False)  # 1 month rolling window
    pc.add_event_listener("hour",   24,  1_000, noop, noop, initial_event_state=False)  # 1 day rolling window
    pc.add_event_listener("minute", 60,    200, noop, noop, initial_event_state=False)  # 1 hour rolling window

    # make sure the pc has some data before we start. we pick a 1-month period to match the listeners in the above.
    for point in buckets_to_points_in_time(
        generate_bursty_data(num_buckets=350, expected_nr_of_bursts=10),
        datetime(2021, 10, 15, tzinfo=timezone.utc),
        datetime(2021, 11, 15, 10, 5, tzinfo=timezone.utc),
        10_000,
            ):

        pc.inc(point)

    # now we start the test: we generate a bursty data-set for a 1-day period, and see how long it takes to evaluate
    points = buckets_to_points_in_time(
        generate_bursty_data(num_buckets=25, expected_nr_of_bursts=5),
        datetime(2021, 11, 15, 10, 5, tzinfo=timezone.utc),
        datetime(2021, 11, 16, 10, 5, tzinfo=timezone.utc),
        1000)

    with passed_time() as t:
        for point in points:
            pc.inc(point)

    print(f"""## PeriodCounter.inc()

1_000 iterations of PeriodCounter.inc() in {t.elapsed:.3f}ms. (when 3 event-listeners are active). I'm not sure exactly
what a good performance would be here, but I can say the following: this means when a 1,000 events happen in a second,
the period-counter uses up 10% of the budget. A first guess would be: this is good enough.""")


print_thoughts_about_prev_tup()
print_thoughts_about_inc()
print_thoughts_about_event_evaluation()
