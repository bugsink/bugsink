import logging
from contextlib import contextmanager
from io import BytesIO
from django.db import models
from django.db import transaction

from functools import partial

from bugsink.streams import copy_stream_limited

from .storage_registry import get_write_storage, get_storage
from .object_kinds import (
    get_object_kind_for_model, get_object_kind_spec, get_object_storage_backend, get_object_storage_key)


logger = logging.getLogger("bugsink.objectstorage")


def _binary_to_bytes(value):
    # psycopg may return BinaryField values as memoryview objects; callers here expect plain bytes.
    if isinstance(value, memoryview):
        return bytes(value)
    return value


class Chunk(models.Model):
    checksum = models.CharField(max_length=40, unique=True)  # unique implies index, which we also use for lookups
    size = models.PositiveIntegerField()
    data = models.BinaryField(null=False)  # as with Events, we can "eventually" move this out of the database
    created_at = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)

    def __str__(self):
        return self.checksum


def get_storage_todo_for_instance(instance):
    object_kind = get_object_kind_for_model(instance.__class__)
    key = get_object_storage_key(instance, object_kind)
    storage_backend = get_object_storage_backend(instance)
    return object_kind, key, storage_backend


def resolve_storage_for_instance(instance):
    object_kind, key, storage_backend = get_storage_todo_for_instance(instance)
    storage = None if storage_backend is None else get_storage(object_kind, storage_backend)
    return object_kind, key, storage_backend, storage


class StorageAwareQuerySet(models.QuerySet):

    def delete(self):
        object_kind = get_object_kind_for_model(self.model)
        object_kind_spec = get_object_kind_spec(object_kind)
        todos = list(
            self.exclude(storage_backend=None).values_list(
                object_kind_spec["key_field"],
                "storage_backend",
            )
        )

        result = super().delete()

        if todos:
            cleanup_objects_on_storage((object_kind, key, storage_backend) for key, storage_backend in todos)

        return result


class File(models.Model):
    # NOTE: since we do single-chunk uploads, optimizations are imaginable. Make it work first though

    checksum = models.CharField(max_length=40, unique=True)  # unique implies index, which we also use for lookups

    # the filename is not unique, nor meaningful in the sense that you could use it to identify the file. It is only
    # here for convenience, i.e. to eye-ball the file in a list. note that we store by checksum, and the filename gets
    # associated on the first successful store. i.e. it's possible that a file would be stored again with a different
    # name but that would go undetected by us. all that is to say: convenience thingie without strong guarantees.
    filename = models.CharField(max_length=255)

    size = models.PositiveIntegerField()
    data = models.BinaryField(null=False)  # as with Events, we can "eventually" move this out of the database
    storage_backend = models.CharField(max_length=255, blank=True, null=True, default=None, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)
    accessed_at = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)

    objects = StorageAwareQuerySet.as_manager()

    def __str__(self):
        return self.filename

    @contextmanager
    def open_for_read(self):
        _, key, _, storage = resolve_storage_for_instance(self)

        if storage is None:
            yield BytesIO(_binary_to_bytes(self.data))
            return

        with storage.open(key, "rb") as f:
            yield f

    def get_raw_data(self):
        with self.open_for_read() as f:
            return f.read()

    def delete(self, *args, **kwargs):
        object_kind, key, storage_backend = get_storage_todo_for_instance(self)
        if storage_backend is not None:
            cleanup_objects_on_storage([(object_kind, key, storage_backend)])

        return super().delete(*args, **kwargs)


def write_to_storage(object_kind, key, data):
    with get_write_storage(object_kind).open(key, "wb") as f:
        f.write(data)


def write_fileobj_to_storage(object_kind, key, fileobj):
    with get_write_storage(object_kind).open(key, "wb") as f:
        copy_stream_limited(fileobj, f)


def cleanup_objects_on_storage(todos):
    todos = list(todos)  # force evaluation _inside_ the transaction (on_commit the todos will be gone otherwise)
    transaction.on_commit(partial(_cleanup_objects_on_storage, todos))


def _cleanup_objects_on_storage(todos):
    for object_kind, key, storage_backend in todos:
        try:
            get_storage(object_kind, storage_backend).delete(key)
        except Exception as e:
            logger.error("Error during cleanup of %s on %s: %s", key, storage_backend, e)


class FileMetadata(models.Model):
    file = models.ForeignKey(File, null=False, on_delete=models.CASCADE, related_name="metadatas")

    # debug_id & file_type nullability: such data exists in manifest.json; we are future-proof for it although we
    # currently don't store it as such.
    debug_id = models.UUIDField(max_length=40, null=True, blank=True)
    file_type = models.CharField(max_length=255, null=True, blank=True)
    data = models.TextField()  # we just dump the rest in here; let's see how much we really need.
    created_at = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)

    def __str__(self):
        # somewhat useless when debug_id is None; but that's not the case we care about ATM
        return f"debug_id: {self.debug_id} ({self.file_type})"

    class Meta:
        # it's _imaginable_ that the below does not actually hold (we just trust the CLI, after all), but that wouldn't
        # make any sense, so we just enforce a property that makes sense. Pro: lookups work. Con: if the client sends
        # garbage, this is not exposed.
        unique_together = (("debug_id", "file_type"),)
