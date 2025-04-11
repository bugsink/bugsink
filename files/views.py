from zipfile import ZipFile
import json
from hashlib import sha1
from gzip import GzipFile
from io import BytesIO
from os.path import basename

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import user_passes_test

from sentry.assemble import ChunkFileState

from bugsink.app_settings import get_settings

from .models import Chunk, File, FileMetadata


_KIBIBYTE = 1024
_MEBIBYTE = 1024 * _KIBIBYTE


class NamedBytesIO(BytesIO):
    def __init__(self, data, name):
        super().__init__(data)
        self.name = name


def get_chunk_upload_settings(request, organization_slug):
    # Sentry / Sentry-CLI has a whole bunch of logic surrounding URLs, which I do not understand and which presumably
    # doesn't make it past Bugsink's cost/benefit-analysis. feature-completeness. For now, we just return our own URL
    # which seems to "just work". If we ever want to go down this path :
    #
    # https://github.com/getsentry/sentry/pull/7095/files <= upload-url-prefix: introduced, but rationale not explained
    #
    # 2 more starting points for the whole "relative" idea
    # * https://github.com/getsentry/sentry-cli/issues/839
    # * https://github.com/getsentry/sentry/pull/29347
    url = get_settings().BASE_URL + "/api/0/organizations/" + organization_slug + "/chunk-upload/"

    # Our "chunk_upload" is chunked in name only; i.e. we only "speak chunked" for the purpose of API-compatability with
    # sentry-cli, but we provide params here such that that cli will only send a single chunk.

    return JsonResponse({
        "url": url,

        # For now, staying close to the default MAX_ENVELOPE_COMPRESSED_SIZE, which is 20MiB;
        # I _think_ I saw a note somewhere on (one of) these values having to be a power of 2; hence 32 here.
        #
        # When implementing uploading, it was done to support sourcemaps. It seems that over at Sentry, the reason they
        # went so complicated in the first place was to enable DIF support (hunderds of MiB regularly).
        "chunkSize": 32 * _MEBIBYTE,
        "maxRequestSize": 32 * _MEBIBYTE,

        # I didn't check the supposed relationship between maxRequestSize and maxFileSize, but assume something similar
        # to what happens w/ envelopes; hence harmonizing with MAX_ENVELOPE_SIZE (and rounding up to a power of 2) here
        "maxFileSize": 128 * _MEBIBYTE,

        # force single-chunk by setting these to 1.
        "concurrency": 1,
        "chunksPerRequest": 1,

        "hashAlgorithm": "sha1",
        "compression": ["gzip"],

        "accept": [
            # I don't claim to fully understand how the sentry-cli switches based on these advertised capabilities, but
            # the list below works for now. Any understanding that I did gain is documented.
            # for a full list of types we _could_ accept, see src/sentry/api/endpoints/chunk.py
            #

            # If the below is off, sentry-cli complains "A release slug is required". Because release-less artifacts are
            # actually the simpler thing, that's undesirable. Other consequences of turning it on have not been charted
            # yet.
            "release_files",

            # this would seem to be the "javascript sourcemaps" thing, but how exactly I did not check yet.
            "sources",

            # https://github.com/getsentry/sentry/discussions/46967
            # artifact_bundles is a concept originating from sentry that uses debug_ids to link maps & sources. Despite
            # it being relatively new, it's my _first_ target for getting sourcemaps to work, because it's actually the
            # most simple and reliable thing (uuid, bidirectional mapping)
            "artifact_bundles",

            # AFAIU the only thing _v2 would signify is the ability to "Implement de-duplication with chunking in the
            # assemble endpoint for artifact bundles (#51224)". Which is needlessly complex from my point of view.
            # "artifact_bundles_v2",

            # the rest of the options are below:
            # "debug_files",
            # "release_files",
            # "pdbs",
            # "bcsymbolmaps",
            # "il2cpp",
            # "portablepdbs",
            # "artifact_bundles",
            # "proguard",
        ]
    })


@csrf_exempt
def chunk_upload(request, organization_slug):
    # TODO authenticate
    # Bugsink has a single-organization model; we simply ignore organization_slug
    # NOTE: we don't check against chunkSize, maxRequestSize and chunksPerRequest (yet), we expect the CLI to behave.

    if request.method == "GET":
        # a GET at this endpoint returns a dict of settings that the CLI takes into account when uploading
        return get_chunk_upload_settings(request, organization_slug)

    # POST: upload (full-size) "chunks" and store them as Chunk objects; file.name whould be the sha1 of the content.
    chunks = []
    if request.FILES:
        chunks = request.FILES.getlist("file")

        # NOTE: we read the whole unzipped file into memory; we _could_ take an approach like bugsink/streams.py.
        # (Note that, because of the auth layer in front, we're slightly less worried about adverserial scenarios)
        chunks += [
            NamedBytesIO(GzipFile(fileobj=file_gzip, mode="rb").read(), name=file_gzip.name)
            for file_gzip in request.FILES.getlist("file_gzip")]

    for chunk in chunks:
        data = chunk.getvalue()

        if sha1(data).hexdigest() != chunk.name:
            raise Exception("checksum mismatch")

        _, _ = Chunk.objects.get_or_create(
            checksum=chunk.name,
            defaults={
                "size": len(data),
                "data": data,  # NOTE: further possible optimization: don't even read the file when already existing
            })

    open('/tmp/chunk.zip', "wb").write(data)  # TODO: remove this line; it's just for debugging

    return HttpResponse()


def assemble_artifact_bundle(bundle_checksum, chunk_checksums):
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


@csrf_exempt  # we're in API context here; this could potentially be pulled up to a higher level though
def artifact_bundle_assemble(request, organization_slug):
    # TODO authenticate
    # Bugsink has a single-organization model; we simply ignore organization_slug

    # NOTE a JSON-schema for this endpoint is available under Apache 2 license (2 year anniversary rule) at
    # https://github.com/getsentry/sentry/blob/8df7543848b4/src/sentry/api/endpoints/organization_artifactbundle_assemble.py#L24
    # (not worth the trouble of extracting right now, since our /sentry dir contains BSD-3 licensed code (2019 version)

    data = json.loads(request.body)
    assemble_artifact_bundle(data["checksum"], data["chunks"])

    # NOTE sentry & glitchtip _always_ return an empty list for "missingChunks" in this view; I don't really understand
    # what's being achieved with that, but it seems to be the expected behavior. Working hypothesis: this was introduced
    # for DIF uploads, and the present endpoint doesn't use it at all. Not even for "v2", surprisingly.

    # NOTE: as it stands, we process the bundle inline, so arguably we could return "OK" here too; "CREATED" is what
    # sentry returns though, so for faithful mimicking it's the safest bet.
    return JsonResponse({"state": ChunkFileState.CREATED, "missingChunks": []})


@user_passes_test(lambda u: u.is_superuser)
def download_file(request, checksum):
    file = File.objects.get(checksum=checksum)
    response = HttpResponse(file.data, content_type="application/octet-stream")
    response["Content-Disposition"] = f"attachment; filename={file.filename}"
    return response
