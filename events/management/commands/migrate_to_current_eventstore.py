from django.core.management.base import BaseCommand
from django.db import transaction
import signal

from bugsink.transaction import immediate_atomic

from events.storage_registry import get_write_storage, get_storage
from events.models import Event


# some thoughts:
# * should be small enough not to hog everything
BATCH_SIZE = 100


class Command(BaseCommand):
    # This is a Command rather than a migration because the current EVENT_STORAGE is a point of configuration, rather
    # than being tied to the evolution of Bugsink itself (i.e. tied to git-history/release-history) as DB migrations are

    help = """'Migrate' event data storage to the currently configured USE_FOR_WRITE"""

    def handle(self, *args, **options):
        self.stopped = False

        signal.signal(signal.SIGINT, self.handle_sigint)

        target_storage = get_write_storage()
        target_storage_name = target_storage.name if target_storage is not None else None

        migrated = 0
        with transaction.atomic():  # explicit is better than implicit for transaction management
            total = Event.objects.all().count()
            todo = Event.objects.exclude(storage_backend=target_storage_name).count()

        print("Migrating {} events to {} (out of {} total events)".format(todo, target_storage_name, total))

        while not self.stopped:
            with immediate_atomic():
                events = Event.objects.exclude(storage_backend=target_storage_name).order_by('id')[:BATCH_SIZE]
                if not events:
                    break

                for cnt, event in enumerate(events):
                    current_storage = get_storage(event.storage_backend) if event.storage_backend else None

                    if current_storage is None:
                        source_data = event.data
                        event.data = ""
                    else:
                        with current_storage.open(event.id, 'r') as source:
                            source_data = source.read()
                        current_storage.delete(event.id)

                    if target_storage is None:
                        event.data = source_data
                    else:
                        with target_storage.open(event.id, 'w') as target:
                            target.write(source_data)

                    event.storage_backend = target_storage_name
                    event.save()

                    if self.stopped:
                        break  # make ^C react per-event rather than per-batch

                migrated += cnt + 1
                print("Migrated {} / {} events".format(migrated, todo))

        if self.stopped:
            # todo - migrated may be incorrect as per the comment below; however, when ^C-ing I don't want to make the
            # user wait on the outcome of a possibly expensive query.
            print("Interrupted; migrated {} events to {}; {} events remain.".format(
                migrated, target_storage_name, todo - migrated))
        else:
            print("Done migrating; migrated {} events to {}; no more events remain.".format(
                migrated, target_storage_name))

        # if migrated != todo:
        # because we operate in BATCH_SIZE-size batches on a running DB, the actually processed
        # number of events needs not match the numbers reported at the beginning. No matter, what's important is that
        # the actual migration is correct.

    def handle_sigint(self, signum, frame):
        self.stopped = True
