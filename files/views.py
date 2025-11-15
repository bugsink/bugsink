import json
from hashlib import sha1
from gzip import GzipFile
from io import BytesIO
import logging

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import user_passes_test
from django.http import Http404

from sentry.assemble import ChunkFileState

from bugsink.app_settings import get_settings
from bugsink.transaction import durable_atomic, immediate_atomic
from bugsink.streams import handle_request_content_encoding
from bsmain.models import AuthToken

from .models import Chunk, File, FileMetadata
from .tasks import assemble_artifact_bundle, assemble_file
from .minidump import extract_dif_metadata

logger = logging.getLogger("bugsink.api")


_KIBIBYTE = 1024
_MEBIBYTE = 1024 * _KIBIBYTE
_GIBIBYTE = 1024 * _MEBIBYTE


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

    return JsonResponse({
        "url": url,

        # We pick a "somewhat arbitrary" value between 1MiB and 16MiB to balance between "works reliably" and "lower
        # overhead", erring on the "works reliably" side of that spectrum. There's really no lower bound technically,
        # I've played with 32-byte requests.
        # note: sentry-cli <= v2.39.1 requires a power of 2 here.
        # chunkSize == maxRequestSize per the comments on `chunksPerRequest: 1`.
        "chunkSize": 2 * _MEBIBYTE,
        "maxRequestSize": 2 * _MEBIBYTE,

        # The limit here is _actually storing this_. For now "just picking a high limit" assuming that we'll have decent
        # storage (#151) for the files eventually.
        "maxFileSize": 2 * _GIBIBYTE,

        # In our current setup increasing concurrency doesn't help (single-writer architecture) while coming at the cost
        # of potential reliability issues. Current codebase has works just fine with it _in principle_ (tested by
        # setting concurrency=10, chunkSize=32, maxRequestSize=32 and adding a sleep(random(..)) in chunk_upload (right
        # before return, and seeing that sentry-cli fires a bunch of things in parallel and artifact_bundle_assemble as
        # a final step.
        "concurrency": 1,

        # There _may_ be good reasons to support multiple chunks per request, but I haven't found a reason to
        # distinguish between chunkSize and maxRequestSize yet, so I'd rather keep them synced for easier reasoning.
        # Current codebase has been observed to work just fine with it though (tested w/ chunkSize=32 and
        # chunksPerRequest=100 and seeing sentry-cli do a single request with many small chunks).
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

            # on second reading I would say: this is "actual source code", but I did not check yet and "don't touch it"
            # (even though we don't actually have an implementation for sources yet)
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
            "debug_files",
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
        # "file" and "file_gzip" are both possible multi-value keys for uploading (with associated semantics each)
        chunks = request.FILES.getlist("file")

        # NOTE: we read the whole unzipped file into memory; we _could_ take an approach like bugsink/streams.py.
        # (Note that, because of the auth layer in front, we're slightly less worried about adverserial scenarios)
        chunks += [
            NamedBytesIO(GzipFile(fileobj=file_gzip, mode="rb").read(), name=file_gzip.name)
            for file_gzip in request.FILES.getlist("file_gzip")]

    for chunk in chunks:
        data = chunk.getvalue()

        # usedforsecurity=False: sha1 is not used cryptographically, and it's part of the protocol, so we use it as is.
        if sha1(data, usedforsecurity=False).hexdigest() != chunk.name:
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


@csrf_exempt  # we're in API context here; this could potentially be pulled up to a higher level though
@requires_auth_token
def difs_assemble(request, organization_slug, project_slug):
    if not get_settings().FEATURE_MINIDUMPS:
        return JsonResponse({"detail": "minidumps not enabled"}, status=404)

    # TODO move to tasks.something.delay
    # TODO think about the right transaction around this
    data = json.loads(request.body)

    file_checksums = set(data.keys())

    existing_files = {
        file.checksum: file
        for file in File.objects.filter(checksum__in=file_checksums)
    }

    all_requested_chunks = {
        chunk
        for file_info in data.values()
        for chunk in file_info.get("chunks", [])
    }

    available_chunks = set(
        Chunk.objects.filter(checksum__in=all_requested_chunks).values_list("checksum", flat=True)
    )

    response = {}

    for file_checksum, file_info in data.items():
        if file_checksum in existing_files:
            response[file_checksum] = {
                "state": ChunkFileState.OK,
                "missingChunks": [],
                # if it is ever needed, we could add something akin to the below, but so far we've not seen client-side
                # actually using this; let's add it on-demand.
                # "dif": json_repr_with_key_info_about(existing_files[file_checksum]),
            }
            continue

        file_chunks = file_info.get("chunks", [])

        # the sentry-cli sends an empty "chunks" list when just polling for file existence; since we already handled the
        # case of existing files above, we can simply return NOT_FOUND here.
        if not file_chunks:
            response[file_checksum] = {
                "state": ChunkFileState.NOT_FOUND,
                "missingChunks": [],
            }
            continue

        missing_chunks = [c for c in file_chunks if c not in available_chunks]
        if missing_chunks:
            response[file_checksum] = {
                "state": ChunkFileState.NOT_FOUND,
                "missingChunks": missing_chunks,
            }
            continue

        file, _ = assemble_file(file_checksum, file_chunks, filename=file_info["name"])

        symbolic_metadata = extract_dif_metadata(file.data)

        FileMetadata.objects.get_or_create(
            debug_id=file_info.get("debug_id"),  # TODO : .get implies "no debug_id", but in that case it's useless
            file_type=symbolic_metadata["kind"],  # NOTE: symbolic's kind goes into file_type...
            defaults={
                "file": file,
                "data": "{}",  # this is the "catch all" field but I don't think we have anything in this case.
            }
        )

        response[file_checksum] = {
            "state": ChunkFileState.OK,
            "missingChunks": [],
        }

    return JsonResponse(response)


@user_passes_test(lambda u: u.is_superuser)
@durable_atomic
def download_file(request, checksum):
    file = File.objects.get(checksum=checksum)
    response = HttpResponse(file.data, content_type="application/octet-stream")
    response["Content-Disposition"] = f"attachment; filename={file.filename}"
    return response


# Note: the below 2 views are not strictly "files" API views, but since the idea of "API Compatibility beyond ingest"
# is basically files-only (and the views below are about API compatibility), they live here.

@csrf_exempt
def api_catch_all(request, subpath):
    # This is a catch-all for unimplemented API endpoints. It logs the request details and raises a 404 (if
    # API_LOG_UNIMPLEMENTED_CALLS is set).

    # the existance of this view (and the associated URL pattern) has the effect of `APPEND_SLASH=False` for our API
    # endpoints, which is a good thing: for API enpoints you generally don't want this kind of magic (explicit breakage
    # is desirable for APIs, and redirects don't even work for POST/PUT data)
    MAX_API_CATCH_ALL_SIZE = 1_000_000  # security and usability meet at this value (or below)
    handle_request_content_encoding(request, MAX_API_CATCH_ALL_SIZE)

    if not get_settings().API_LOG_UNIMPLEMENTED_CALLS:
        raise Http404("Unimplemented API endpoint: /api/" + subpath)

    lines = [
        "Unimplemented API usage:",
        f"  Path:   /api/{subpath}",
        f"  Method: {request.method}",
    ]

    interesting_meta_keys = ["CONTENT_TYPE", "CONTENT_LENGTH", "HTTP_TRANSFER_ENCODING"]
    interesting_headers = {
        k: request.META[k] for k in interesting_meta_keys if k in request.META
    }

    if interesting_headers:
        lines.append("  Headers:")
        for k, v in interesting_headers.items():
            lines.append(f"    {k}: {v}")

    if request.GET:
        lines.append(f"  GET:    {request.GET.dict()}")

    content_type = request.META.get("CONTENT_TYPE", "")
    if content_type == "application/x-www-form-urlencoded" or content_type.startswith("multipart/form-data"):
        if request.POST:
            lines.append(f"  POST:   {request.POST.dict()}")
        if request.FILES:
            lines.append(f"  FILES:  {[f.name for f in request.FILES.values()]}")

    else:
        body = request.read(MAX_API_CATCH_ALL_SIZE)
        decoded = body.decode("utf-8", errors="replace").strip()

        if content_type == "application/json":
            shown_pretty = False
            try:
                parsed = json.loads(decoded)
                pretty = json.dumps(parsed, indent=2)
                lines.append("  JSON body:")
                lines.extend(f"    {line}" for line in pretty.splitlines())
                shown_pretty = True
            except json.JSONDecodeError:
                pass

        if not shown_pretty:
            lines.append("  Body:")
            lines.append(f"    {body}")

    logger.info("\n".join(lines))
    raise Http404("Unimplemented API endpoint: /api/" + subpath)


@csrf_exempt
@requires_auth_token
def api_root(request):
    # the results of this endpoint mimick what Sentry does for the GET on the /api/0/ path; we simply did a request on
    # their endpoint and hardcoded the result below.

    # This endpoint has some use in that sentry-cli uses it to check for token validity in the `login` flow (see #97)

    # Bugsink currently only has Bugsink-wide tokens (superuser tokens) which best map to "org" tokens. Sentry's
    # org-tokens "currently have a limited set of scopes", in particular they _only_ support 'org:ci' which maps to
    # "Source Map Upload, Release Creation", which is exactly what we allow too.

    # Returning the below for valid tokens makes sentry-cli say "Valid org token", which is great. And our failure for
    # "@requires_auth_token" makes it say "Invalid token" which is also great.
    return JsonResponse({
        "version": "0",
        "auth": {
            "scopes": ["org:ci"]},
        "user": None,
    })
