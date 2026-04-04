import re
import logging
import tempfile
from datetime import timedelta
from zipfile import ZipFile
import json
from hashlib import sha1
from os.path import basename
from pathlib import Path
from django.utils import timezone

from compat.timestamp import parse_timestamp
from snappea.decorators import shared_task

from bugsink.transaction import immediate_atomic, delay_on_commit
from bugsink.app_settings import get_settings
from bugsink.streams import copy_stream_limited

from .models import Chunk, File, FileMetadata, write_fileobj_to_storage, _binary_to_bytes
from .storage_registry import get_write_storage

logger = logging.getLogger("bugsink.api")


# budget is not yet tuned; reasons for high values: we're dealing with "leaves in the model-dep-tree here"; reasons for
# low values: deletion of files might just be expensive.
VACUUM_FILES_BATCH_SIZE = 500


# "In the wild", we have run into non-unique debug IDs (one in code, one in comment-at-bottom). This regex matches a
# known pattern for "one in code", such that we can at least warn if it's not the same at the actually reported one.
# See #157
IN_CODE_DEBUG_ID_REGEX = re.compile(
    rb'e\._sentryDebugIds\[.*?\]\s*=\s*["\']([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})["\']'
)
DEBUG_ID_SCAN_TAIL_SIZE = 64 * 1024


def create_file_from_local_path(checksum, filename, size, local_path):
    write_storage = get_write_storage("file")
    file, created = File.objects.get_or_create(
        checksum=checksum,
        defaults={
            "size": size,
            "data": b"" if write_storage is not None else local_path.read_bytes(),
            "filename": filename,
            "storage_backend": None if write_storage is None else write_storage.name,
        })

    if created and write_storage is not None:
        with local_path.open("rb") as f:
            write_fileobj_to_storage("file", checksum, f)

    return file, created


def read_limited_bytes(input_stream, max_bytes):
    with tempfile.SpooledTemporaryFile(max_size=max_bytes + 1) as output_stream:
        bytes_read = copy_stream_limited(
            input_stream,
            output_stream,
            max_bytes=max_bytes,
            reason=f"MAX_FILE_SIZE: {max_bytes}",
        )
        output_stream.seek(0)
        return output_stream.read(), bytes_read


def extract_zip_entry_to_path(bundle_zip, entry_name, local_path, max_bytes):
    # usedforsecurity=false: sha1 is not used cryptographically, it's part of the protocol, so we use it as is.
    checksum = sha1(usedforsecurity=False)

    with bundle_zip.open(entry_name) as input_stream:
        with local_path.open("wb") as output_stream:
            size = copy_stream_limited(
                input_stream,
                output_stream,
                max_bytes=max_bytes,
                reason=f"MAX_FILE_SIZE: {max_bytes}",
                digest=checksum,
            )

    return checksum.hexdigest(), size


def find_in_code_debug_ids(local_path):
    matches = set()
    tail = b""

    with local_path.open("rb") as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break

            haystack = tail + chunk
            if len(haystack) > DEBUG_ID_SCAN_TAIL_SIZE:
                cutoff = len(haystack) - DEBUG_ID_SCAN_TAIL_SIZE
                scan_bytes = haystack[:cutoff]
                tail = haystack[cutoff:]
            else:
                scan_bytes = b""
                tail = haystack

            matches.update(match.decode("ascii") for match in IN_CODE_DEBUG_ID_REGEX.findall(scan_bytes))

    matches.update(match.decode("ascii") for match in IN_CODE_DEBUG_ID_REGEX.findall(tail))
    return matches


@shared_task
def assemble_artifact_bundle(bundle_checksum, chunk_checksums):
    # arguably, you could just wrap-around each operation, "around everything" guarantees a fully consistent update on
    # the data and we don't do this that often that it's assumed to matter.
    with immediate_atomic():
        # NOTE: as it stands we don't store the (optional) extra info of release/dist.

        # NOTE: there's also the concept of an artifact bundle as _tied_ to a release, i.e. without debug_ids. We don't
        # support that, but if we ever were to support it we'd need a separate method/param to distinguish it.

        bundle_file, _ = assemble_file(bundle_checksum, chunk_checksums, filename=f"{bundle_checksum}.zip")
        max_file_size = get_settings().MAX_FILE_SIZE
        with tempfile.TemporaryDirectory() as tempdir:
            with bundle_file.open_for_read() as f:
                with ZipFile(f) as bundle_zip:
                    with bundle_zip.open("manifest.json") as manifest_stream:
                        manifest_bytes, _ = read_limited_bytes(manifest_stream, max_file_size)
                    manifest = json.loads(manifest_bytes.decode("utf-8"))

                    for zip_entry_name, manifest_entry in manifest["files"].items():
                        # We intentionally do not use the zip entry name directly for path construction here. A stable
                        # digest gives us a local temp filename without having to reason about ".." or similar path
                        # components in untrusted archive entries.
                        local_path = Path(
                            tempdir,
                            sha1(zip_entry_name.encode("utf-8"), usedforsecurity=False).hexdigest(),
                        )
                        checksum, size = extract_zip_entry_to_path(
                            bundle_zip, zip_entry_name, local_path, max_file_size,
                        )

                        filename = basename(manifest_entry.get("url", zip_entry_name))[:255]
                        file, _ = create_file_from_local_path(checksum, filename, size, local_path)

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

                        # the in-code regexes show up in the _minified_ source only (the sourcemap's original source
                        # code will not have been "polluted" with it yet, since it's the original).
                        if file_type == "minified_source":
                            mismatches = find_in_code_debug_ids(local_path) - {debug_id}
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
    max_file_size = get_settings().MAX_FILE_SIZE

    with tempfile.TemporaryDirectory() as tempdir:
        local_path = Path(tempdir, checksum)

        # usedforsecurity=false: sha1 is not used cryptographically, and it's part of the protocol, so we use it as is.
        checksum_state = sha1(usedforsecurity=False)
        size = 0

        with local_path.open("wb") as output_stream:
            for chunk in chunks_in_order:
                chunk_data = _binary_to_bytes(chunk.data)
                next_size = size + len(chunk_data)
                if next_size > max_file_size:
                    raise ValueError("Assembled file exceeds MAX_FILE_SIZE")

                output_stream.write(chunk_data)
                checksum_state.update(chunk_data)
                size = next_size

        if checksum_state.hexdigest() != checksum:
            raise Exception("checksum mismatch")

        file, created = create_file_from_local_path(checksum, filename, size, local_path)

        # the assumption here is: chunks are basically use-once, so we can delete them after use. "in theory" a chunk
        # may be used in multiple files (which are still being assembled) but with chunksizes in the order of 1MiB, I'd
        # say this is unlikely.
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
def vacuum_files(chunk_max_days=1, file_max_days=90):
    if vacuum_files_batch(chunk_max_days=chunk_max_days, file_max_days=file_max_days):
        # possibly more to delete, so we re-schedule the task
        delay_on_commit(vacuum_files, chunk_max_days=chunk_max_days, file_max_days=file_max_days)


def vacuum_files_sync(chunk_max_days=1, file_max_days=90):
    # possibly more to delete, so we re-schedule the task
    while vacuum_files_batch(chunk_max_days=chunk_max_days, file_max_days=file_max_days):
        pass


def vacuum_files_batch(chunk_max_days=1, file_max_days=90):
    # returns True when there may be more work to do.
    with immediate_atomic():
        now = timezone.now()
        num_deleted = 0

        for model, field_name, max_days in [
            (Chunk, 'created_at', chunk_max_days,),
            (File, 'accessed_at', file_max_days),
            # for FileMetadata we rely on cascading from File (which will always happen "eventually")
                ]:

            while num_deleted < VACUUM_FILES_BATCH_SIZE:
                ids = list(
                    model.objects
                    .filter(**{f"{field_name}__lt": now - timedelta(days=max_days)})[:VACUUM_FILES_BATCH_SIZE]
                    .values_list('id', flat=True)
                )

                if len(ids) == 0:
                    break

                model.objects.filter(id__in=ids).delete()
                num_deleted += len(ids)

        # budget exhausted but possibly more to delete
        return num_deleted == VACUUM_FILES_BATCH_SIZE
