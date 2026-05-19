import logging
from contextlib import contextmanager
from io import BytesIO
from django.db import models
from django.db import transaction
from django.db.models import Q

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

    # FileMetadata as provided by the client (e.g. in a manifest); security-wise any facts noted here are not guaranteed
    # to be correct / cannot be trusted. Our security boundary is: FileMetadata is bound to a Project, so you can only
    # pollute your own Project's FileMetadata.
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.DO_NOTHING)

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
        # The below is basically the ["project", "debug_id", "file_type"] uniqueness constraint we want, but with a
        # twist to allow legacy data without project. We can remove the legacy constraint after a long transition
        # period, e.g. May 2027, at which point the first constraint can be simplified to a normal uniqueness constraint
        # on the three fields. (just the single unique_together constraint doesn't work because of the nullability of
        # project, which would allow multiple entries with the same debug_id and file_type but null project because
        # nulls are not considered equal in SQL)
        constraints = [
            models.UniqueConstraint(
                fields=["project", "debug_id", "file_type"],
                condition=Q(project__isnull=False, debug_id__isnull=False, file_type__isnull=False),
                name="filemeta_project_debug_type",
            ),
            models.UniqueConstraint(
                fields=["debug_id", "file_type"],
                condition=Q(project__isnull=True, debug_id__isnull=False, file_type__isnull=False),
                name="filemeta_legacy_debug_type",
            ),
        ]


def get_file_metadata_for_debug_ids(project, debug_ids, file_type):
    """Return {debug_id: FileMetadata} for debug files visible to project."""
    debug_ids = set(debug_ids)
    if not debug_ids:
        return {}

    result = {
        metadata.debug_id: metadata
        for metadata in FileMetadata.objects.filter(
            project=project,
            debug_id__in=debug_ids,
            file_type=file_type,
        ).select_related("file")
    }

    missing_debug_ids = debug_ids - set(result)
    if missing_debug_ids:
        # Compatibility for sourcemaps/debug files uploaded before project-scoped metadata existed. This keeps old
        # installs working for now, but should be removed after a long transition period, e.g. May 2027.
        result.update({
            metadata.debug_id: metadata
            for metadata in FileMetadata.objects.filter(
                project__isnull=True,
                debug_id__in=missing_debug_ids,
                file_type=file_type,
            ).select_related("file")
        })

    return result


def get_file_metadata_for_debug_id(project, debug_id, file_type):
    result = list(get_file_metadata_for_debug_ids(project, [debug_id], file_type).values())
    if len(result) == 0:
        return None

    if len(result) > 1:
        # Should be prevented by database constraints; getting here would mean our lookup logic is wrong.
        raise RuntimeError("Multiple FileMetadata objects found for one debug_id")

    return result[0]
