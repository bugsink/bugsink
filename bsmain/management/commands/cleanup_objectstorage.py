import signal
import sys

from django.core.management.base import BaseCommand
from django.db import transaction

from bugsink.app_settings import get_settings
from files.object_kinds import get_object_kind_model, get_object_kind_spec
from files.storage_registry import get_storage


class Command(BaseCommand):
    help = """Clean up object storage by removing stored objects that have no database equivalent."""

    def add_arguments(self, parser):
        parser.add_argument("object_kind", type=str, help="Object kind to clean up, e.g. 'file'")
        parser.add_argument("storage_name", type=str, help="Storage name to clean up")

    def handle(self, *args, **options):
        self.stopped = False
        signal.signal(signal.SIGINT, self.handle_sigint)

        object_kind = options["object_kind"]
        storage_name = options["storage_name"]

        object_kind_spec = get_object_kind_spec(object_kind)
        model = get_object_kind_model(object_kind)
        key_field = object_kind_spec["key_field"]

        configured_object_storages = get_settings().OBJECT_STORAGES.get(object_kind, {})
        configured_storage_names = configured_object_storages.keys()
        available_storages = ", ".join(configured_storage_names)

        if storage_name not in configured_storage_names:
            if not configured_storage_names:
                print(
                    f"Storage name {storage_name} not found because you have not configured any object storage for "
                    f"{object_kind}."
                )
                sys.exit(1)

            print(
                f"Storage name {storage_name} not found for {object_kind}. "
                f"Available storage names: {available_storages}"
            )
            sys.exit(1)

        storage = get_storage(object_kind, storage_name)

        delete_count = 0
        checked_count = 0

        for key in storage.list():
            if self.stopped:
                break

            checked_count += 1

            with transaction.atomic():
                if self.stopped:
                    break

                if model.objects.filter(**{key_field: key, "storage_backend": storage_name}).count() == 0:
                    print(f"Deleting {object_kind} data {key}")
                    storage.delete(key)
                    delete_count += 1

            if checked_count % 100 == 0:
                print(f"Processed {checked_count} items from the storage.")

        print()
        if self.stopped:
            print(
                f"Checked {checked_count} {object_kind} objects, deleted {delete_count} from the storage; interrupted."
            )
        else:
            print(f"Checked {checked_count} {object_kind} objects, deleted {delete_count} from the storage; done.")

    def handle_sigint(self, signum, frame):
        self.stopped = True
