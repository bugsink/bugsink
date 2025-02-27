from django.core.management.base import BaseCommand

from bugsink.transaction import immediate_atomic
from events.models import Event
from tags.models import digest_tags


class Command(BaseCommand):
    help = """Read all Tag-related data from the Events in the database and update the Tags in the DB accordingly."""

    def handle(self, *args, **options):
        for event in Event.objects.all():
            # transaction per event: allows for interrupting the process without losing all progress; also allows for
            # your server to remain responsive during the process
            with immediate_atomic():
                # "in principle" we should refetch event here because we get a fresh transaction; in practice we only
                # read from the event, and the event_data (the part we care about) is write-once anyway (unchanging
                # after digest).

                digest_tags(event.get_parsed_data(), event, event.issue)
