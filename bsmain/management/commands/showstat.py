from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum, Max

from bugsink.transaction import durable_atomic
from snappea.models import Task, Stat
from events.models import Event


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            "stat",
            choices=[
                "snappea-queue-size",
                "event_count",
                "snappea-stats",
                "digestion_speed",
            ],
        )
        parser.add_argument(
            "--task-name",
            help="Task name to filter by (snappea-stats only)",
            default=None,
        )

        parser.add_argument(
            "--window",
            help="Window size in minutes (snappea-stats only)",
            type=int,
            default=None,
        )

    def handle(self, *args, **options):
        stat = options["stat"]

        if stat == "snappea-queue-size":
            print(Task.objects.all().count())

        if stat == "event_count":
            with durable_atomic():
                print(Event.objects.all().count())

        if stat == "snappea-stats":
            return self.snappea_stats(options["task_name"], options["window"])

        if stat == "digestion_speed":
            # NOTE: is this still a valuable stat? snappea_stat for "digest" task is more useful, I'd say. esp. given
            # the warning
            print("WARNING: when eviction is enabled, the numbers will be wrong")

            now = timezone.now()
            with durable_atomic():
                for window in [1, 10, 30, 60, 5 * 60, 60 * 60, 24 * 60 * 60]:
                    qs = Event.objects.filter(digested_at__gte=now - timedelta(seconds=window))
                    digested_in_window = qs.count()
                    # (safe assumption: digestion is done in order; this is "safe enough" (perhaps with a tiny rounding
                    # error) because of the snappea queue, which is a FIFO queue); the rounding error is in the
                    # insertion in the queue, but it's not a big deal for some counts

                    if digested_in_window == 0:
                        continue

                    first = qs.order_by("digested_at").first()
                    last = qs.order_by("digested_at").last()

                    digestion_window = (last.digested_at - first.digested_at).total_seconds()
                    ingestion_window = (last.ingested_at - first.ingested_at).total_seconds()

                    if digestion_window <= 0:
                        continue

                    if window / digestion_window > 1.2:
                        print(f"{digested_in_window} events digested last {digestion_window:.1f}s "
                              f"({digested_in_window / digestion_window:.1f}/s)")
                    else:
                        print(f"{digested_in_window} events digested last ~{window}s "
                              f"({digested_in_window / digestion_window:.1f}/s)")

                    if ingestion_window <= 0:
                        print("  (no window)")
                        continue

                    factor = digestion_window / ingestion_window
                    print(f"  ingestion window: {ingestion_window:.1f}s, factor: {factor:.1f}")

    def snappea_stats(self, filter_task_name, window=None):
        now_floor = datetime(*(datetime.now(timezone.utc).timetuple()[:5]), tzinfo=timezone.utc)

        print("""past n minutes  task                                              AVG                 SAT    MAX
                                                  done/s err/s   wall   wait  write   sat   wall   wait  write backlog""")  # noqa

        windows = [1, 2, 5, 10, 60, 5 * 60, 24 * 60] if window is None else [window]

        with durable_atomic(using="snappea"):
            for window in windows:
                since = now_floor - timedelta(minutes=window)
                seconds_in_window = 60 * window

                base_qs = Stat.objects.filter(timestamp__gte=since, timestamp__lt=now_floor)
                if filter_task_name:
                    base_qs = base_qs.filter(task_name__endswith="." + filter_task_name)

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
                for stat in stats:
                    stat["write_saturation"] = stat["write_time"] / seconds_in_window

                    for field in ["wall_time", "wait_time", "write_time"]:
                        stat[field] /= stat["done"]

                    for field in ["done", "errors"]:
                        stat[field] /= seconds_in_window

                    task_name = stat["task_name"].split(".")[-1]

                    # len("send_project_invite_email_new_user") == 34
                    print(f"{window:<4}            "
                          f"{task_name:<34} "
                          f"{stat['done']:5.1f} "
                          f"{stat['errors']:5.1f} "
                          f"{stat['wall_time']:6.3f} "
                          f"{stat['wait_time']:6.3f} "
                          f"{stat['write_time']:6.3f}  "
                          f"{stat['write_saturation']:3.2f} "
                          f"{stat['max_wall_time']:6.3f} "
                          f"{stat['max_wait_time']:6.3f} "
                          f"{stat['max_write_time']:6.3f} " +
                          (f"{stat['max_task_count']:9d}" if stat["max_task_count"] else "  v. many")
                          )
