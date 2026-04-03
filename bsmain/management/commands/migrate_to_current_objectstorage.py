import signal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.utils import OperationalError

from bugsink.transaction import immediate_atomic

from files.models import cleanup_objects_on_storage
from files.object_kinds import (
    get_object_kind_model,
    get_object_kind_spec,
    get_object_storage_backend,
    get_object_storage_key,
    set_object_stored_data,
)
from files.storage_registry import get_storage, get_write_storage, validate_storage_names


BATCH_SIZE = 100


class Command(BaseCommand):
    help = """Migrate object data storage to the currently configured USE_FOR_WRITE for the given object kind"""

    def add_arguments(self, parser):
        parser.add_argument("object_kind", type=str, help="Object kind to migrate, e.g. 'file'")

    def handle(self, *args, **options):
        self.stopped = False
        signal.signal(signal.SIGINT, self.handle_sigint)

        object_kind = options["object_kind"]
        object_kind_spec = get_object_kind_spec(object_kind)
        model = get_object_kind_model(object_kind)

        target_storage = get_write_storage(object_kind)
        target_storage_name = target_storage.name if target_storage is not None else None

        migrated = 0
        self._validate_referenced_storages(model, object_kind)

        with transaction.atomic():
            total = "many"
            todo = "many"
            try:
                total = model.objects.all().count()
                todo = model.objects.exclude(storage_backend=target_storage_name).count()
            except OperationalError as e:
                if e.args[0] != "interrupted":
                    raise

        print(f"Migrating {todo} {object_kind} objects to {target_storage_name} (out of {total} total objects)")

        while not self.stopped:
            with immediate_atomic():
                objects = (
                    model.objects
                    .exclude(storage_backend=target_storage_name)
                    .order_by("id")[:BATCH_SIZE]
                )
                if not objects:
                    break

                source_cleanup_todos = []
                for cnt, obj in enumerate(objects):
                    key = get_object_storage_key(obj, object_kind)
                    current_storage_backend = get_object_storage_backend(obj)
                    current_storage = (
                        get_storage(object_kind, current_storage_backend)
                        if current_storage_backend else None
                    )

                    if current_storage is None:
                        source_data = getattr(obj, object_kind_spec["raw_data_getter"])()
                    else:
                        with current_storage.open(key, "rb") as source:
                            source_data = source.read()

                    if target_storage is None:
                        set_object_stored_data(obj, object_kind, source_data)
                    else:
                        with target_storage.open(key, "wb") as target:
                            target.write(source_data)
                        set_object_stored_data(obj, object_kind, b"")

                    obj.storage_backend = target_storage_name
                    obj.save()

                    if current_storage_backend is not None:
                        source_cleanup_todos.append((object_kind, key, current_storage_backend))

                    if self.stopped:
                        break

                if source_cleanup_todos:
                    cleanup_objects_on_storage(source_cleanup_todos)

                migrated += cnt + 1
                print(f"Migrated {migrated} / {todo} {object_kind} objects")

        if self.stopped:
            remaining = todo - migrated if isinstance(todo, int) else f"unknown number of {object_kind}"
            print(f"Interrupted; migrated {migrated} objects to {target_storage_name}; {remaining} remain.")
        else:
            print(f"Done migrating; migrated {migrated} objects to {target_storage_name}; no more objects remain.")

    def handle_sigint(self, signum, frame):
        self.stopped = True

    def _validate_referenced_storages(self, model, object_kind):
        storage_names = (
            model.objects
            .exclude(storage_backend=None)
            .values_list("storage_backend", flat=True)
            .distinct()
        )

        try:
            validate_storage_names(object_kind, storage_names)
        except ValueError as e:
            raise CommandError(f"Cannot migrate {object_kind} objects; {e}")
