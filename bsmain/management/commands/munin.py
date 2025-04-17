from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum, Max

from bugsink.transaction import durable_atomic
from snappea.models import Stat


class Command(BaseCommand):
    """Stats that come in a format that's pre-made for munin."""
    # heavily based on (copied from) showstat

    def add_arguments(self, parser):
        parser.add_argument(
            "stat",
            choices=[
                "begin-avg",
                "begin-max",
                "immediate-avg",
                "immediate-max",
                "digested-count",
                # avg-wall-time (for digest) ... not so relevant, because it mostly expresses waiting
            ],
        )

    def handle(self, *args, **options):
        stat = options["stat"]
        return self.snappea_stats(stat)

    def snappea_stats(self, munin_field):
        FIELD_MAP = {
            "begin-avg": "wait_time",
            "begin-max": "max_wait_time",
            "immediate-avg": "write_time",
            "immediate-max": "max_write_time",
            "digested-count": "done",
        }

        now = datetime.now(timezone.utc)
        # we work based on one minute ago. Reason: the last minute may not have been written yet. We prefer the
        # imprecision of being one minute "late" (reporting shifted by 1 minute) over inconsistencies that would be
        # caused by sometimes missing the most recent minute.
        one_minute_ago = now - timedelta(minutes=1)
        end = datetime(*(one_minute_ago.timetuple()[:5]), tzinfo=timezone.utc)

        task_name = "ingest.tasks.digest"

        with durable_atomic(using="snappea"):
            window = 5
            since = end - timedelta(minutes=window)
            seconds_in_window = 60 * window

            base_qs = Stat.objects.filter(timestamp__gte=since, timestamp__lt=end).filter(task_name=task_name)

            stats = base_qs.values(
                "task_name",
            ).annotate(
                done=Sum("done"),
                errors=Sum("errors"),
                wall_time=Sum("wall_time"),
                wait_time=Sum("wait_time"),
                write_time=Sum("write_time"),
                max_wall_time=Max("max_wall_time"),
                max_wait_time=Max("max_wait_time"),
                max_write_time=Max("max_write_time"),
                max_task_count=Max("task_count"),
            )

            try:
                stat = stats[0]

                for field in ["wall_time", "wait_time", "write_time"]:
                    stat[field] /= stat["done"]

                for field in ["done", "errors"]:
                    stat[field] /= seconds_in_window

                task_name = stat["task_name"].split(".")[-1]

                print(stat[FIELD_MAP[munin_field]])

            except IndexError:
                # no data for this time period
                print("U")
