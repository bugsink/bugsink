import json
from hashlib import sha1
from gzip import GzipFile
from io import BytesIO

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import user_passes_test

from sentry.assemble import ChunkFileState

from bugsink.app_settings import get_settings
from bugsink.transaction import durable_atomic, immediate_atomic
from bsmain.models import AuthToken

from .models import Chunk, File
from .tasks import assemble_artifact_bundle


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


def requires_auth_token(view_function):
    # {"error": "..."} (status=401) response is API-compatible; for that to work we need the present function to be a
    # decorator (so we can return, rather than raise, which plain-Django doesn't support for 401)

    def first_require_auth_token(request, *args, **kwargs):
        header_value = request.META.get("HTTP_AUTHORIZATION")
        if not header_value:
            return JsonResponse({"error": "Authorization header not found"}, status=401)

        header_values = header_value.split()

        if len(header_values) != 2:
            return JsonResponse(
                {"error": "Expecting 'Authorization: Token abc123...' but got '%s'" % header_value}, status=401)

        the_word_bearer, token = header_values

        if AuthToken.objects.filter(token=token).count() < 1:
            return JsonResponse({"error": "Invalid token"}, status=401)

        return view_function(request, *args, **kwargs)

    first_require_auth_token.__name__ = view_function.__name__
    return first_require_auth_token


@csrf_exempt
@requires_auth_token
def chunk_upload(request, organization_slug):
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

        with immediate_atomic():  # a snug fit around the only DB-writing thing we do here to ensure minimal blocking
            _, _ = Chunk.objects.get_or_create(
                checksum=chunk.name,
                defaults={
                    "size": len(data),
                    "data": data,  # NOTE: further possible optimization: don't even read the file when already existing
                })

    return HttpResponse()


@csrf_exempt  # we're in API context here; this could potentially be pulled up to a higher level though
@requires_auth_token
def artifact_bundle_assemble(request, organization_slug):
    # Bugsink has a single-organization model; we simply ignore organization_slug

    # NOTE a JSON-schema for this endpoint is available under Apache 2 license (2 year anniversary rule) at
    # https://github.com/getsentry/sentry/blob/8df7543848b4/src/sentry/api/endpoints/organization_artifactbundle_assemble.py#L24
    # (not worth the trouble of extracting right now, since our /sentry dir contains BSD-3 licensed code (2019 version)

    data = json.loads(request.body)
    assemble_artifact_bundle.delay(data["checksum"], data["chunks"])

    # NOTE sentry & glitchtip _always_ return an empty list for "missingChunks" in this view; I don't really understand
    # what's being achieved with that, but it seems to be the expected behavior. Working hypothesis: this was introduced
    # for DIF uploads, and the present endpoint doesn't use it at all. Not even for "v2", surprisingly.

    # In the ALWAYS_EAGER setup, we process the bundle inline, so arguably we could return "OK" here too; "CREATED" is
    # what sentry returns though, so for faithful mimicking it's the safest bet.
    return JsonResponse({"state": ChunkFileState.CREATED, "missingChunks": []})


@user_passes_test(lambda u: u.is_superuser)
@durable_atomic
def download_file(request, checksum):
    file = File.objects.get(checksum=checksum)
    response = HttpResponse(file.data, content_type="application/octet-stream")
    response["Content-Disposition"] = f"attachment; filename={file.filename}"
    return response
