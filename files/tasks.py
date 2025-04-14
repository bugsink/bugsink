from zipfile import ZipFile
import json
from hashlib import sha1
from io import BytesIO
from os.path import basename

from snappea.decorators import shared_task
from bugsink.transaction import immediate_atomic

from .models import Chunk, File, FileMetadata


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

            checksum = sha1(file_data).hexdigest()

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
                # such records exist and we could store them, but we don't, since we don't have a purpose for them.
                continue

            FileMetadata.objects.get_or_create(
                debug_id=debug_id,
                file_type=file_type,
                defaults={
                    "file": file,
                    "data": json.dumps(manifest_entry),
                }
            )

        # NOTE we _could_ get rid of the file at this point (but we don't). Ties in to broader questions of retention.


def assemble_file(checksum, chunk_checksums, filename):
    """Assembles a file from chunks"""

    # NOTE: unimplemented checks/tricks
    # * total file-size v.s. some max
    # * explicit check chunk availability (as it stands, our processing is synchronous, so no need)
    # * skip-on-checksum-exists

    chunks = Chunk.objects.filter(checksum__in=chunk_checksums)
    chunks_dicts = {chunk.checksum: chunk for chunk in chunks}
    chunks_in_order = [chunks_dicts[checksum] for checksum in chunk_checksums]  # implicitly checks chunk availability
    data = b"".join([chunk.data for chunk in chunks_in_order])

    if sha1(data).hexdigest() != checksum:
        raise Exception("checksum mismatch")

    return File.objects.get_or_create(
        checksum=checksum,
        defaults={
            "size": len(data),
            "data": data,
            "filename": filename,
        })
