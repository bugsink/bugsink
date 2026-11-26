import json
import logging
from collections import defaultdict
from uuid import UUID

from django.db import migrations

from bugsink.transaction import immediate_atomic
from events.storage_registry import get_storage


EVENT_BATCH_SIZE = 25
METADATA_BATCH_SIZE = 100
logger = logging.getLogger("bugsink.migrations")


def referenced_debug_ids(data):
    if not isinstance(data, dict) or not isinstance(data.get("debug_meta"), dict):
        return set()
    images = data["debug_meta"].get("images")
    if not isinstance(images, list):
        return set()

    result = set()
    for image in images:
        if not isinstance(image, dict):
            continue
        try:
            result.add(UUID(image.get("debug_id")))
        except (ValueError, TypeError, AttributeError):
            continue
    return result


def scope_legacy_file_metadata(apps, schema_editor):
    # References cannot prove ownership, but these projects already have access through the global legacy fallback.
    # Preserve that use before removing the fallback; do not replace explicit project-scoped uploads.
    FileMetadata = apps.get_model("files", "FileMetadata")
    Event = apps.get_model("events", "Event")
    using = schema_editor.connection.alias
    metadata = FileMetadata.objects.using(using)
    legacy_debug_ids = set(metadata.filter(project__isnull=True).values_list("debug_id", flat=True)) - {None}
    if not legacy_debug_ids:
        return

    # Event payloads (including external storage reads) are scanned without holding the write lock.
    events = Event.objects.using(using).filter(project__is_deleted=False).order_by("pk")
    last_pk = None
    skipped = 0
    while True:
        batch = list((events if last_pk is None else events.filter(pk__gt=last_pk)).values(
            "pk", "project_id", "data", "storage_backend")[:EVENT_BATCH_SIZE])
        if not batch:
            break
        last_pk = batch[-1]["pk"]
        project_debug_ids = defaultdict(set)
        for event in batch:
            try:
                if event["storage_backend"] is None:
                    data = json.loads(event["data"])
                else:
                    with get_storage(event["storage_backend"]).open(event["pk"], "r") as f:
                        data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
                skipped += 1
                continue
            project_debug_ids[event["project_id"]].update(referenced_debug_ids(data) & legacy_debug_ids)

        for project_id, debug_ids in project_debug_ids.items():
            debug_ids = list(debug_ids)
            for offset in range(0, len(debug_ids), METADATA_BATCH_SIZE):
                ids = debug_ids[offset:offset + METADATA_BATCH_SIZE]
                with immediate_atomic(using=using):
                    existing = set(metadata.filter(project_id=project_id, debug_id__in=ids).values_list(
                        "debug_id", "file_type"))
                    new_metadata = []
                    for legacy in metadata.filter(project__isnull=True, debug_id__in=ids).order_by("pk"):
                        key = (legacy.debug_id, legacy.file_type)
                        if key in existing:
                            continue
                        existing.add(key)
                        new_metadata.append(FileMetadata(
                            project_id=project_id, debug_id=legacy.debug_id, file_type=legacy.file_type,
                            file_id=legacy.file_id, data=legacy.data))
                    metadata.bulk_create(new_metadata)

    if skipped:
        logger.warning("Skipped %s missing or invalid event payloads while scoping legacy file metadata.", skipped)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("files", "0007_chunk_storage_backend"),
        ("events", "0030_backfill_event_counts_per_hour"),
    ]

    operations = [
        migrations.RunPython(scope_legacy_file_metadata, migrations.RunPython.noop),
    ]
