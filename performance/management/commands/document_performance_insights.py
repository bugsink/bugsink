from django.core.management.base import BaseCommand

import random
import time
from datetime import datetime, timezone

from django.conf import settings

from bugsink.period_counter import _prev_tup, PeriodCounter
from performance.bursty_data import generate_bursty_data, buckets_to_points_in_time
from bugsink.registry import get_pc_registry

from projects.models import Project
from issues.models import Issue
from events.models import Event


# this file is the beginning of an approach to getting a handle on performance.


class Command(BaseCommand):
    help = "..."

    def handle(self, *args, **options):
        if "performance" not in str(settings.DATABASES["default"]["NAME"]):
            raise ValueError("This command should only be run on the performance-test database")

        print_thoughts_about_prev_tup()
        print_thoughts_about_inc()
        print_thoughts_about_event_evaluation()
        print_thoughts_about_pc_registry()


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
the period-counter uses up 3% of the budget. A first guess would be: this is good enough.""")


def print_thoughts_about_pc_registry():
    # note: in load_performance_insights we use minimal (non-data-containing) events here. this may not be
    # representative of real world performance. having said that: this immediately triggers the thought that for real
    # initialization only timestamps and issue_ids are needed, and that we should adjust the code accordingly

    with passed_time() as t:
        get_pc_registry()

    print(f"""## get_pc_registry()

getting the pc-registry takes {t.elapsed:.3f}ms. (with the default fixtures, which contain

* { Project.objects.count() } projects,
* { Issue.objects.count() } issues,
* { Event.objects.count() } events

This means (surprisingly) we can take our eye off optimizing this particular part of code (for now), because:

* in the (expected) production setup where we we cut ingestion and handling in 2 parts, 6s delay on the handling server
  boot is fine.
* in the debugserver (integrated ingestion/handling) we don't expect 100k events; and even if we did a 6s delay on the
  first event/request is fine.

Counterpoint: on playground.bugsink.com I just observed 42s to initalize 150k events, which is ~5 times more slow than
the above. It's also a "real hiccup". Anyway, there's too many questions about period counter (e.g. how to share
across processes, or the consequences of quota) to focus on this particular point first.

Ways forward once we do decide to improve:

* regular saving of state (savepoint in time, with "unhandled after") (the regularity of saving is left as an exercise
  to the reader)
* more granular caching/loading, e.g. load per project/issue on demand
""")
