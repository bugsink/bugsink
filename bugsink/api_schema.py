SENTRY_ENVELOPE_DOCS_URL = "https://develop.sentry.dev/sdk/envelopes/#data-model"
BUGSINK_SOURCEMAPS_DOCS_URL = "https://www.bugsink.com/docs/sourcemaps/"


def _path_parameter(name, description, schema_type="string"):
    return {
        "in": "path",
        "name": name,
        "schema": {"type": schema_type},
        "required": True,
        "description": description,
    }


def _response(description, schema=None):
    response = {"description": description}
    if schema is not None:
        response["content"] = {
            "application/json": {
                "schema": schema,
            },
        }
    return response


def _object_schema(properties=None, required=None, additional_properties=True):
    schema = {
        "type": "object",
        "additionalProperties": additional_properties,
    }
    if properties:
        schema["properties"] = properties
    if required:
        schema["required"] = required
    return schema


def _sentry_auth_description(extra=""):
    description = (
        "This endpoint exists for Sentry SDK compatibility. Authenticate with Sentry SDK auth: "
        "`X-Sentry-Auth` or `?sentry_key=...`."
    )
    if extra:
        description += " " + extra
    return description


def _csp_auth_description():
    return (
        "This endpoint accepts browser-emitted CSP violation reports from the `report-uri` directive. "
        "Authenticate with `?sentry_key=...`; browsers cannot set custom auth headers on CSP report posts."
    )


def _sentry_security():
    return [
        {"SentryAuthHeader": []},
        {"SentryKeyQuery": []},
    ]


def _bearer_security():
    return [{"BearerAuth": []}]


def _json_request(schema, description=None, content_type="application/json"):
    result = {
        "required": True,
        "content": {
            content_type: {
                "schema": schema,
            },
        },
    }
    if description is not None:
        result["description"] = description
    return result


def _id_response(description="Accepted event id."):
    return _response(
        description,
        _object_schema(
            properties={"id": {"type": "string"}},
            required=["id"],
            additional_properties=False,
        ),
    )


def _error_response(description):
    return _response(
        description,
        _object_schema(
            properties={
                "message": {"type": "string"},
                "detail": {"type": "string"},
                "error": {"type": "string"},
            },
        ),
    )


def _project_parameter():
    return _path_parameter("project_pk", "Integer Bugsink project id.", "integer")


def _organization_parameter():
    return _path_parameter("organization_slug", "Organization slug accepted for sentry-cli compatibility.")


def _compatibility_paths():
    chunk_state_schema = _object_schema(
        properties={
            "state": {"type": "string"},
            "missingChunks": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        required=["state", "missingChunks"],
        additional_properties=False,
    )

    return {
        "/api/0/": {
            "get": {
                "operationId": "sentry_compatible_api_root_retrieve",
                "tags": ["Sentry-compatible API"],
                "security": _bearer_security(),
                "summary": "Support sentry-cli login checks",
                "description": (
                    "This endpoint exists because sentry-cli probes Sentry's API root during its login flow. "
                    "Bugsink returns the minimal Sentry-like org-token response needed for sentry-cli to accept a "
                    "Bugsink auth token for release and sourcemap upload commands."
                ),
                "responses": {
                    "200": _response(
                        "Token is valid.",
                        _object_schema(
                            properties={
                                "version": {"type": "string"},
                                "auth": _object_schema(
                                    properties={
                                        "scopes": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    required=["scopes"],
                                    additional_properties=False,
                                ),
                                "user": {"nullable": True},
                            },
                            required=["version", "auth", "user"],
                            additional_properties=False,
                        ),
                    ),
                    "401": _error_response("Authorization token is missing or invalid."),
                },
            },
        },
        "/api/0/organizations/{organization_slug}/chunk-upload/": {
            "get": {
                "operationId": "sentry_compatible_chunk_upload_settings_retrieve",
                "tags": ["Sentry-compatible API"],
                "security": _bearer_security(),
                "summary": "Get sentry-cli chunk upload settings",
                "description": (
                    "This endpoint exists for sentry-cli sourcemap upload support. "
                    "See the Bugsink sourcemaps documentation."
                ),
                "externalDocs": {
                    "description": "Bugsink sourcemaps documentation",
                    "url": BUGSINK_SOURCEMAPS_DOCS_URL,
                },
                "parameters": [_organization_parameter()],
                "responses": {
                    "200": _response(
                        "Chunk upload settings for sentry-cli.",
                        _object_schema(
                            properties={
                                "url": {"type": "string", "format": "uri"},
                                "chunkSize": {"type": "integer"},
                                "maxRequestSize": {"type": "integer"},
                                "maxFileSize": {"type": "integer"},
                                "concurrency": {"type": "integer"},
                                "chunksPerRequest": {"type": "integer"},
                                "hashAlgorithm": {"type": "string"},
                                "compression": {"type": "array", "items": {"type": "string"}},
                                "accept": {"type": "array", "items": {"type": "string"}},
                            },
                            required=[
                                "url",
                                "chunkSize",
                                "maxRequestSize",
                                "maxFileSize",
                                "concurrency",
                                "chunksPerRequest",
                                "hashAlgorithm",
                                "compression",
                                "accept",
                            ],
                            additional_properties=False,
                        ),
                    ),
                    "401": _error_response("Authorization token is missing or invalid."),
                },
            },
            "post": {
                "operationId": "sentry_compatible_chunk_upload_create",
                "tags": ["Sentry-compatible API"],
                "security": _bearer_security(),
                "summary": "Upload sentry-cli file chunks",
                "description": (
                    "This endpoint exists for sentry-cli sourcemap upload support. "
                    "It accepts chunk files named by sha1 checksum. See the Bugsink sourcemaps documentation."
                ),
                "externalDocs": {
                    "description": "Bugsink sourcemaps documentation",
                    "url": BUGSINK_SOURCEMAPS_DOCS_URL,
                },
                "parameters": [_organization_parameter()],
                "requestBody": _json_request(
                    _object_schema(),
                    description="Multipart form data with `file` and/or `file_gzip` file fields.",
                    content_type="multipart/form-data",
                ),
                "responses": {
                    "200": _response("Chunks accepted."),
                    "401": _error_response("Authorization token is missing or invalid."),
                    "413": _error_response("Uploaded chunk is too large."),
                },
            },
        },
        "/api/0/organizations/{organization_slug}/artifactbundle/assemble/": {
            "post": {
                "operationId": "sentry_compatible_artifact_bundle_assemble_create",
                "tags": ["Sentry-compatible API"],
                "security": _bearer_security(),
                "summary": "Assemble a sentry-cli artifact bundle",
                "description": (
                    "This endpoint exists for sentry-cli sourcemap upload support. "
                    "It reports missing chunks or queues artifact bundle assembly. "
                    "See the Bugsink sourcemaps documentation."
                ),
                "externalDocs": {
                    "description": "Bugsink sourcemaps documentation",
                    "url": BUGSINK_SOURCEMAPS_DOCS_URL,
                },
                "parameters": [_organization_parameter()],
                "requestBody": _json_request(
                    _object_schema(
                        properties={
                            "checksum": {"type": "string"},
                            "chunks": {"type": "array", "items": {"type": "string"}},
                            "projects": {"type": "array", "items": {"type": "string"}},
                        },
                        required=["checksum", "chunks", "projects"],
                    ),
                ),
                "responses": {
                    "200": _response("Assembly state.", chunk_state_schema),
                    "400": _error_response("Project information is missing or invalid."),
                    "401": _error_response("Authorization token is missing or invalid."),
                },
            },
        },
        "/api/0/projects/{organization_slug}/{project_slug}/files/difs/assemble/": {
            "post": {
                "operationId": "sentry_compatible_difs_assemble_create",
                "tags": ["Sentry-compatible API"],
                "security": _bearer_security(),
                "summary": "Assemble sentry-cli debug information files",
                "description": (
                    "This endpoint exists for Sentry native debug file upload compatibility through sentry-cli. "
                    "Bugsink uses the same file upload machinery as sourcemaps where possible."
                ),
                "parameters": [
                    _organization_parameter(),
                    _path_parameter("project_slug", "Existing Bugsink project slug."),
                ],
                "requestBody": _json_request(
                    _object_schema(
                        additional_properties=_object_schema(
                            properties={
                                "chunks": {"type": "array", "items": {"type": "string"}},
                                "name": {"type": "string"},
                                "debug_id": {"type": "string"},
                            },
                        ),
                    ),
                ),
                "responses": {
                    "200": _response(
                        "Per-file assembly state.",
                        _object_schema(additional_properties=chunk_state_schema),
                    ),
                    "401": _error_response("Authorization token is missing or invalid."),
                    "404": _error_response("Minidumps are disabled or the project does not exist."),
                },
            },
        },
        "/api/{project_pk}/store/": {
            "post": {
                "operationId": "sentry_compatible_store_create",
                "tags": ["Sentry-compatible API"],
                "security": _sentry_security(),
                "summary": "Ingest an event through Sentry's deprecated store endpoint",
                "description": _sentry_auth_description(
                    "This is Sentry's deprecated event ingestion endpoint, kept for compatibility with older SDKs. "
                    "Prefer the envelope endpoint when using SDKs that support it."
                ),
                "parameters": [_project_parameter()],
                "requestBody": _json_request(_object_schema(), description="Sentry event JSON."),
                "responses": {
                    "200": _id_response(),
                    "400": _error_response("Event payload is invalid."),
                    "403": _error_response("Project auth failed."),
                    "413": _error_response("Event payload is too large."),
                    "429": _response("Ingestion rate limit exceeded."),
                },
            },
        },
        "/api/{project_pk}/envelope/": {
            "post": {
                "operationId": "sentry_compatible_envelope_create",
                "tags": ["Sentry-compatible API"],
                "security": _sentry_security(),
                "summary": "Ingest a Sentry envelope",
                "description": _sentry_auth_description(
                    "This is the primary Sentry SDK ingestion endpoint. "
                    "Envelope DSN authentication is also accepted when present in the envelope headers."
                ),
                "externalDocs": {
                    "description": "Sentry envelope data model",
                    "url": SENTRY_ENVELOPE_DOCS_URL,
                },
                "parameters": [_project_parameter()],
                "requestBody": _json_request(
                    {"type": "string", "format": "binary"},
                    description="Sentry envelope payload.",
                    content_type="application/x-sentry-envelope",
                ),
                "responses": {
                    "200": _response("Envelope accepted. Event envelopes may return `{id: ...}`."),
                    "400": _error_response("Envelope payload is invalid."),
                    "403": _error_response("Project auth failed."),
                    "413": _error_response("Envelope payload is too large."),
                    "429": _response("Ingestion rate limit exceeded."),
                },
            },
        },
        "/api/{project_pk}/minidump/": {
            "post": {
                "operationId": "sentry_compatible_minidump_create",
                "tags": ["Sentry-compatible API"],
                "security": _sentry_security(),
                "summary": "Ingest a Sentry native minidump",
                "description": _sentry_auth_description(
                    "This endpoint exists for Sentry native/minidump upload compatibility."
                ),
                "parameters": [_project_parameter()],
                "requestBody": _json_request(
                    _object_schema(
                        properties={"upload_file_minidump": {"type": "string", "format": "binary"}},
                        required=["upload_file_minidump"],
                    ),
                    description="Multipart form data containing `upload_file_minidump`.",
                    content_type="multipart/form-data",
                ),
                "responses": {
                    "200": _id_response(),
                    "400": _error_response("Minidump payload is invalid."),
                    "403": _error_response("Project auth failed."),
                    "404": _error_response("Minidumps are disabled."),
                },
            },
        },
        "/api/{project_pk}/security/": {
            "post": {
                "operationId": "csp_report_create",
                "tags": ["CSP reporting"],
                "security": [{"SentryKeyQuery": []}],
                "summary": "Ingest a CSP report",
                "description": _csp_auth_description(),
                "parameters": [_project_parameter()],
                "requestBody": _json_request(
                    _object_schema(
                        properties={"csp-report": _object_schema()},
                        required=["csp-report"],
                    ),
                    description="CSP report JSON.",
                    content_type="application/csp-report",
                ),
                "responses": {
                    "200": _response("CSP report accepted."),
                    "400": _error_response("CSP report payload is invalid."),
                    "403": _error_response("Project auth failed."),
                    "413": _error_response("CSP report is too large."),
                    "429": _response("Ingestion rate limit exceeded."),
                },
            },
        },
    }


def _tag_names_from_paths(paths):
    for operations in paths.values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            for tag in operation.get("tags", []):
                yield tag


def _ensure_tag(tags, name, description=None):
    if any(tag.get("name") == name for tag in tags):
        return

    tag = {"name": name}
    if description is not None:
        tag["description"] = description
    tags.append(tag)


def add_sentry_compatible_api(result, generator, **kwargs):
    paths = result.setdefault("paths", {})

    tags = result.setdefault("tags", [])
    for tag in _tag_names_from_paths(paths):
        _ensure_tag(tags, tag)

    _ensure_tag(
        tags,
        "Sentry-compatible API",
        (
            "`/api/0` and `/api/{project_pk}/` paths exist for Sentry-SDK / sentry-cli compatibility "
            "(as opposed to the `/api/canonical/` paths which are Bugsink-specific)."
        ),
    )
    _ensure_tag(
        tags,
        "CSP reporting",
        (
            "Native support for browser CSP violation reports emitted through the `report-uri` directive. "
            "Reports are translated into Bugsink events and processed through the normal ingest pipeline."
        ),
    )

    for path, operations in _compatibility_paths().items():
        paths.pop(path, None)
        paths[path] = operations

    security_schemes = result.setdefault("components", {}).setdefault("securitySchemes", {})
    security_schemes.setdefault("SentryAuthHeader", {
        "type": "apiKey",
        "in": "header",
        "name": "X-Sentry-Auth",
    })
    security_schemes.setdefault("SentryKeyQuery", {
        "type": "apiKey",
        "in": "query",
        "name": "sentry_key",
    })

    return result
