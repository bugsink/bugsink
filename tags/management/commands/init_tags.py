import time
import signal

from django.core.management.base import BaseCommand

from bugsink.transaction import immediate_atomic
from events.models import Event
from tags.models import digest_tags


class Command(BaseCommand):
    help = """Read all Tag-related data from the Events in the database and update the Tags in the DB accordingly."""

    def handle(self, *args, **options):
        self.stopped = False
        signal.signal(signal.SIGINT, self.handle_sigint)

        total = Event.objects.count()
        t0 = time.time()

        try:
            for i, event in enumerate(Event.objects.all().iterator()):
                # transaction per event: allows for interrupting the process without losing all progress; also allows
                # for your server to remain responsive during the process
                with immediate_atomic():
                    # "in principle" we should refetch event here because we get a fresh transaction; in practice we
                    # only read from the event, and the event_data (the part we care about) is write-once anyway
                    # (unchanging after digest).

                    digest_tags(event.get_parsed_data(), event, event.issue)

                if (i + 1) % 1_000 == 0:
                    print(f"Processed {i + 1}/{total} events")

                if self.stopped:
                    break

        finally:
            print(f"Processed {i + 1}/{total} events in {time.time() - t0:.2f}s at "
                  f"{i / (time.time() - t0):.2f} events/s")

    def handle_sigint(self, signum, frame):
        self.stopped = True
