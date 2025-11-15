import re
import logging
from datetime import timedelta
from zipfile import ZipFile
import json
from hashlib import sha1
from io import BytesIO
from os.path import basename
from django.utils import timezone

from compat.timestamp import parse_timestamp
from snappea.decorators import shared_task

from bugsink.transaction import immediate_atomic, delay_on_commit
from bugsink.app_settings import get_settings

from .models import Chunk, File, FileMetadata

logger = logging.getLogger("bugsink.api")


# "In the wild", we have run into non-unique debug IDs (one in code, one in comment-at-bottom). This regex matches a
# known pattern for "one in code", such that we can at least warn if it's not the same at the actually reported one.
# See #157
IN_CODE_DEBUG_ID_REGEX = re.compile(
    r'e\._sentryDebugIds\[.*?\]\s*=\s*["\']([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})["\']'
)


@shared_task
def assemble_artifact_bundle(bundle_checksum, chunk_checksums):
    # arguably, you could just wrap-around each operation, "around everything" guarantees a fully consistent update on
    # the data and we don't do this that often that it's assumed to matter.
    with immediate_atomic():
        # NOTE: as it stands we don't store the (optional) extra info of release/dist.

        # NOTE: there's also the concept of an artifact bundle as _tied_ to a release, i.e. without debug_ids. We don't
        # support that, but if we ever were to support it we'd need a separate method/param to distinguish it.

        bundle_file, _ = assemble_file(bundle_checksum, chunk_checksums, filename=f"{bundle_checksum}.zip")

        bundle_zip = ZipFile(BytesIO(bundle_file.data))  # NOTE: in-memory handling of zips.
        manifest_bytes = bundle_zip.read("manifest.json")
        manifest = json.loads(manifest_bytes.decode("utf-8"))

        for filename, manifest_entry in manifest["files"].items():
            file_data = bundle_zip.read(filename)

            # usedforsecurity=false: sha1 is not used cryptographically, it's part of the protocol, so we use it as is.
            checksum = sha1(file_data, usedforsecurity=False).hexdigest()

            filename = basename(manifest_entry.get("url", filename))[:255]

            file, _ = File.objects.get_or_create(
                checksum=checksum,
                defaults={
                    "filename": filename,
                    "size": len(file_data),
                    "data": file_data,
                })

            debug_id = manifest_entry.get("headers", {}).get("debug-id", None)
            file_type = manifest_entry.get("type", None)
            if debug_id is None or file_type is None:
                because = (
                    "it has neither Debug ID nor file-type" if debug_id is None and file_type is None else
                    "it has no Debug ID" if debug_id is None else "it has no file-type")

                logger.warning(
                    "Uploaded file %s will be ignored by Bugsink because %s.",
                    filename,
                    because,
                )

                continue

            FileMetadata.objects.get_or_create(
                debug_id=debug_id,
                file_type=file_type,
                defaults={
                    "file": file,
                    "data": json.dumps(manifest_entry),
                }
            )

            # the in-code regexes show up in the _minified_ source only (the sourcemap's original source code will not
            # have been "polluted" with it yet, since it's the original).
            if file_type == "minified_source":
                mismatches = set(IN_CODE_DEBUG_ID_REGEX.findall(file_data.decode("utf-8"))) - {debug_id}
                if mismatches:
                    logger.warning(
                        "Uploaded file %s contains multiple Debug IDs. Uploaded as %s, but also found: %s.",
                        filename,
                        debug_id,
                        ", ".join(sorted(mismatches)),
                    )

        if not get_settings().KEEP_ARTIFACT_BUNDLES:
            # delete the bundle file after processing, since we don't need it anymore.
            bundle_file.delete()


def assemble_file(checksum, chunk_checksums, filename):
    """Assembles a file from chunks"""

    # NOTE: unimplemented checks/tricks
    # * total file-size v.s. some max
    # * explicit check chunk availability
    # * skip this whole thing when the (whole-file) checksum exists

    chunks = Chunk.objects.filter(checksum__in=chunk_checksums)
    chunks_dicts = {chunk.checksum: chunk for chunk in chunks}
    chunks_in_order = [chunks_dicts[checksum] for checksum in chunk_checksums]  # implicitly checks chunk availability
    data = b"".join([chunk.data for chunk in chunks_in_order])

    # usedforsecurity=false: sha1 is not used cryptographically, and it's part of the protocol, so we use it as is.
    if sha1(data, usedforsecurity=False).hexdigest() != checksum:
        raise Exception("checksum mismatch")

    file, created = File.objects.get_or_create(
        checksum=checksum,
        defaults={
            "size": len(data),
            "data": data,
            "filename": filename,
        })

    # the assumption here is: chunks are basically use-once, so we can delete them after use. "in theory" a chunk may
    # be used in multiple files (which are still being assembled) but with chunksizes in the order of 1MiB, I'd say this
    # is unlikely.
    chunks.delete()
    return file, created


@shared_task
def record_file_accesses(metadata_ids, accessed_at):
    # implemented as a task to get around the fact that file-access happens in an otherwise read-only view (and the fact
    # that the access happened is a write to the DB).

    # a few thoughts on the context of "doing this as a task": [1] the expected througput is relatively low (UI) so the
    # task overhead should be OK [2] it's not "absolutely criticial" to always record this (99% is enough) and [3] it's
    # not related to the reading transaction _at all_ (all we need to record is the fact that it happened.
    #
    # thought on instead pulling it to the top of the UI's view: code-wise, it's annoying but doable (annoying b/c
    # 'for_request_method' won't work anymore). But this would still make this key UI view depend on the write lock
    # which is such a shame for responsiveness so we'll stick with task-based.

    with immediate_atomic():
        parsed_accessed_at = parse_timestamp(accessed_at)

        # note: filtering on IDs comes with "robust for deletions" out-of-the-box (and: 2 queries only)
        file_ids = FileMetadata.objects.filter(id__in=metadata_ids).values_list("file_id", flat=True)
        File.objects.filter(id__in=file_ids).update(accessed_at=parsed_accessed_at)


@shared_task
def vacuum_files():
    now = timezone.now()
    with immediate_atomic():
        # budget is not yet tuned; reasons for high values: we're dealing with "leaves in the model-dep-tree here";
        # reasons for low values: deletion of files might just be expensive.
        budget = 500
        num_deleted = 0

        for model, field_name, max_days in [
            (Chunk, 'created_at', 1,),  # 1 is already quite long... Chunks are used immediately, or not at all.
            (File, 'accessed_at', 90),
            # for FileMetadata we rely on cascading from File (which will always happen "eventually")
                ]:

            while num_deleted < budget:
                ids = (model.objects.filter(**{f"{field_name}__lt": now - timedelta(days=max_days)})[:budget].
                       values_list('id', flat=True))

                if len(ids) == 0:
                    break

                model.objects.filter(id__in=ids).delete()
                num_deleted += len(ids)

        if num_deleted == budget:
            # budget exhausted but possibly more to delete, so we re-schedule the task
            delay_on_commit(vacuum_files)
