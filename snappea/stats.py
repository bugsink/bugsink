from datetime import datetime, timezone, timedelta
import threading
import logging
import sentry_sdk

from django.db import OperationalError
from django.db.models import Count

from sentry_sdk_extensions import capture_or_log_exception
from bugsink.transaction import immediate_atomic
from bugsink.timed_sqlite_backend.base import different_runtime_limit
from performance.context_managers import time_to_logger

from .models import Task, Stat
from .settings import get_settings

logger = logging.getLogger("snappea.foreman")
performance_logger = logging.getLogger("bugsink.performance.snappea")


class Stats:

    def __init__(self):
        self.lock = threading.Lock()
        # initialize to "one minute ago" to ensure reset-at-first-check
        self.last_write_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).timetuple()[:5]
        self.d = {}

    def _ensure_task(self, task_name):
        if task_name not in self.d:
            self.d[task_name] = {
                # we _could_ monitor starts, but my guess is it's not that interesting, since no timings are available,
                # you don't actually gain much insight from the count of started tasks, and you're even in danger of
                # setting people on the wrong track because start/done will differ slightly over the per-minute buckets.
                # "starts": 0,
                "done": 0,
                "errors": 0,
                "wall_time": 0,
                "wait_time": 0,
                "write_time": 0,
                "max_wall_time": 0,
                "max_wait_time": 0,
                "max_write_time": 0,
            }

    def done(self, task_name, wall_time, wait_time, write_time, error):
        # we take "did it error" as a param to enable a single call-side path avoid duplicating taking timings call-side

        try:
            with self.lock:
                self._possibly_write()

                self._ensure_task(task_name)
                self.d[task_name]["done"] += 1
                self.d[task_name]["wall_time"] += wall_time
                self.d[task_name]["wait_time"] += wait_time
                self.d[task_name]["write_time"] += write_time
                self.d[task_name]["max_wall_time"] = max(self.d[task_name]["max_wall_time"], wall_time)
                self.d[task_name]["max_wait_time"] = max(self.d[task_name]["max_wait_time"], wait_time)
                self.d[task_name]["max_write_time"] = max(self.d[task_name]["max_write_time"], write_time)
                if error:
                    self.d[task_name]["errors"] += 1

        except Exception as e:
            # Problems with Stats should _never_ bring down snappea.
            if sentry_sdk.is_initialized():
                # Only for the case where full error is captured to Dogfooded Bugsink, do we want to draw some
                # attention to this; in the other case the big error in the logs (full traceback) is clear enough.
                logger.warning("Snappea Stat Exception: %s", str(e))
            capture_or_log_exception(e, logger)

    def _possibly_write(self):
        # we only write once-a-minute; this means the cost of writing stats is amortized (at least when it matters, i.e.
        # under pressure) by approx 1/(60*30); (the cost (see time_to_logger) was 15ms on my local env in initial tests)
        #
        # "edge" cases, in which nothing is written:
        # * snappea-shutdown
        # * "no new minute" (only happens when there's almost no load, in which case you don't care)
        # but low overhead, robustness and a simple impl are more important than after-the-comma precision.
        # further reason to use separate "Stat" rather than "just write into Task": the latter would incur extra write-
        # pressure on the Snappea DB: because of at-most-once we delete _before_ doing any work, and the stats are only
        # known _after_ the work is done (which would then be the extra write).

        # we look at the clock ourselves, rather than pass this in, such that the looking at the clock happens only
        # once we've grabbed the lock; this ensures our times are monotonicially increasing (assuming no system
        # clock funnyness).
        now = datetime.now(timezone.utc)

        tup = now.timetuple()[:5]  # len("YMDHM")  i.e. cut off at minute
        if tup > self.last_write_at:  # > rather than != means backwards clock drifting is silently/gracefully ignored
            # the Stat w/ timestamp x is for the one-minute bucket from that point in time forwards:
            timestamp = datetime(*(self.last_write_at), tzinfo=timezone.utc)

            self._write(timestamp)

            # re-init:
            self.last_write_at = tup
            self.d = {}

    def _write(self, timestamp):
        if get_settings().STATS_RETENTION_MINUTES == 0:
            # no stats retention; don't write anything either. this won't attempt to clean up either, which is OK in my
            # book
            return

        with time_to_logger(performance_logger, "Snappea write Stats"):
            with immediate_atomic(using="snappea"):  # explicit is better than impl.; and we combine read/write here
                # having stats is great, but I don't want to hog task-processing too long (which would happen
                # precisely when the backlog grows large)
                with different_runtime_limit(0.1, using="snappea"):
                    try:
                        task_counts = Task.objects.values("task_name").annotate(count=Count("task_name"))
                    except OperationalError as e:
                        if e.args[0] != "interrupted":
                            raise
                        task_counts = None  # explicitly "unknown"; which we want to propagate to the stats in that case

                task_counts_d = {d['task_name']: d['count'] for d in task_counts} if task_counts is not None else None

                # store stats; combining the counted 'handled' (done) tasks with the 'counts' (backlog)
                stats = [
                    Stat(
                        timestamp=timestamp,
                        task_name=task_name,
                        task_count=task_counts_d.get(task_name, 0) if task_counts is not None else None,
                        **kwargs,
                    ) for task_name, kwargs in self.d.items()
                ]
                Stat.objects.bulk_create(stats)

                Stat.objects.filter(
                    timestamp__lt=timestamp - timedelta(minutes=get_settings().STATS_RETENTION_MINUTES)).delete()
