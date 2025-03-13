import time
import signal

from django.core.management.base import BaseCommand
from django.db import connection

from bugsink.transaction import immediate_atomic, durable_atomic
from events.models import Event
from tags.models import digest_tags


def get_all_events():
    """
    Fetches all events from the database, but does so in batches to avoid loading all events into memory at once,
    and uses a separate transaction for each batch to avoid self-inflicted checkpoint starvation
    """
    last_digested_at = None
    last_id = None

    while True:
        # as per the notes in snappea/foreman, we close the connection to avoid checkpoint starvation. Whether this is
        # actually necessary is unclear: when I ran into checkpoint starvation in this script, it was self-inflicted (an
        # open cursor for the Event.objects.all() query, and when I solved that particular problem (with get_all_events)
        # the checkpoint starvation went away as well. But it's a good idea to close the connection anyway for good
        # measure; it's not a problem as per the notes in snappea/foreman (we're outside a transaction here).
        connection.close()

        with durable_atomic():
            # digested_at is indexed, and has the nice property that events that come in while this script is running
            # will have a digested_at value that is greater than those already in the database (assuming increasing
            # time, i.e. assuming no clock funny business)
            # we order by id as well to ensure a stable order in case of ties (which at small batch sizes might even
            # lead to no progress being made); the order by id is not indexed, but the ad-hoc ordering will only need
            # to be done for the number of ties to be broken i.e. exactly identical timestamps (which should typically
            # be very small).
            base_qs = Event.objects.order_by("digested_at", "id")
            if last_digested_at is not None:
                events = list(base_qs.filter(digested_at__gt=last_digested_at, id__gt=last_id)[:1000])
            else:
                events = list(base_qs[:1000])

        if not events:
            break

        for event in events:
            yield event

        last_digested_at, last_id = event.digested_at, event.id


class Command(BaseCommand):
    help = """Read all Tag-related data from the Events in the database and update the Tags in the DB accordingly."""

    def handle(self, *args, **options):
        self.stopped = False
        signal.signal(signal.SIGINT, self.handle_sigint)

        total = Event.objects.count()
        t0 = time.time()

        try:
            for i, event in enumerate(get_all_events()):
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
