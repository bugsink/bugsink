from django.core.management.base import BaseCommand
from django.utils import timezone

from bugsink.transaction import durable_atomic
from snappea.models import Task
from events.models import Event


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            "stat",
            choices=[
                "snappea-queue-size",
                "event_count",
                "digestion_speed",
            ],
        )

    def handle(self, *args, **options):
        stat = options["stat"]

        if stat == "snappea-queue-size":
            print(Task.objects.all().count())

        if stat == "event_count":
            with durable_atomic():
                print(Event.objects.all().count())

        if stat == "digestion_speed":
            print("WARNING: when eviction is enabled, the numbers will be wrong")

            for window in [1, 10, 30, 60, 5 * 60, 60 * 60, 24 * 60 * 60]:
                now = timezone.now()
                with durable_atomic():
                    qs = Event.objects.filter(digested_at__gte=now - timezone.timedelta(seconds=window))
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
