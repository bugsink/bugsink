import sys
import signal

from django.core.management.base import BaseCommand
from django.db import transaction

from bugsink.app_settings import get_settings
from events.storage_registry import get_storage
from events.models import Event


class Command(BaseCommand):
    help = """Clean up the event store by removing stored events that have nog Event equivalent."""

    # 'in theory', this happens properly when Event objects are deleted (i.e. as part of eviction), but only in theory
    # are practice and theory the same. In practice, they are not.

    def add_arguments(self, parser):
        parser.add_argument('storage_name', type=str, help='The name of the storage to clean up')

    def handle(self, *args, **options):
        self.stopped = False
        signal.signal(signal.SIGINT, self.handle_sigint)

        storage_names = ",".join(get_settings().EVENT_STORAGES.keys())
        if options['storage_name'] not in storage_names:
            print(f"Storage name {options['storage_name']} not found. Available storage names: {storage_names}")
            sys.exit(1)
        storage = get_storage(options['storage_name'])

        delete_count = 0
        checked_count = 0

        for event_id in storage.list():
            if self.stopped:
                break

            checked_count += 1

            # w.r.t. transactions, I _always_ prefer to be explicit. In this case: read-only, tightly around each query,
            # means we do each check against an as recent-as-possible snapshot.
            with transaction.atomic():
                if self.stopped:
                    break

                if Event.objects.filter(id=event_id, storage_backend=options['storage_name']).count() == 0:
                    print(f"Deleting event data {event_id}")
                    storage.delete(event_id)
                    delete_count += 1

            if checked_count % 100 == 0:
                print(f"Processed {checked_count} items from the storage.")

        print()
        if self.stopped:
            print(f"Checked {checked_count} events, deleted {delete_count} from the storage; interrupted.")
        else:
            print(f"Checked {checked_count} events, deleted {delete_count} from the storage; done.")

    def handle_sigint(self, signum, frame):
        self.stopped = True
