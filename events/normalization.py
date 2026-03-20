from copy import deepcopy


def _is_scalar(value):
    return isinstance(value, (str, int, float, bool))


def _as_string(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float, bool)):
        return str(value)

    return ""


def _normalize_mapping(value):
    if isinstance(value, dict):
        return value

    if isinstance(value, list):
        result = {}
        for item in value:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue

            key, nested_value = item
            if not isinstance(key, str):
                continue

            result[key] = nested_value

        return result

    return {}


def _normalize_frames(value):
    if isinstance(value, list):
        return [frame for frame in value if isinstance(frame, dict)]

    if isinstance(value, dict):
        return [value]

    return []


def _normalize_stacktrace(value, validation_failed):
    stacktrace = _normalize_mapping(value)
    if not stacktrace:
        return {}

    if "frames" in stacktrace or validation_failed:
        stacktrace["frames"] = _normalize_frames(stacktrace.get("frames"))

    return stacktrace


def _normalize_exception(value, validation_failed):
    if isinstance(value, dict):
        value = deepcopy(value)
        if "mechanism" in value or validation_failed:
            value["mechanism"] = _normalize_mapping(value.get("mechanism"))
        if "stacktrace" in value or validation_failed:
            value["stacktrace"] = _normalize_stacktrace(value.get("stacktrace"), validation_failed)
        return value

    if validation_failed and _is_scalar(value):
        return {"value": value}

    return {}


def _normalize_thread(value, validation_failed):
    if not isinstance(value, dict):
        return {}

    value = deepcopy(value)
    if "stacktrace" in value or validation_failed:
        value["stacktrace"] = _normalize_stacktrace(value.get("stacktrace"), validation_failed)
    return value


def _normalize_breadcrumb(value, validation_failed):
    if isinstance(value, dict):
        value = deepcopy(value)
        if "data" in value or validation_failed:
            value["data"] = _normalize_mapping(value.get("data"))
        return value

    if validation_failed and _is_scalar(value):
        return {"message": _as_string(value)}

    return {}


def _normalize_values(value, item_normalizer, validation_failed):
    if value is None:
        return []

    if isinstance(value, dict):
        value = value.get("values", [value])
    elif isinstance(value, tuple):
        value = list(value)
    elif not isinstance(value, list):
        value = [value] if validation_failed else []

    return [item_normalizer(item, validation_failed) for item in value]


def normalize_event_data(data, validation_failed=False):
    """
    Normalize event data for Bugsink's own consumers.

    This is not a generic "fix arbitrary JSON" pass. Validation remains the source of truth.

    We always normalize the documented multi-shape interfaces that Bugsink reads directly:
    * exception / threads / breadcrumbs: list or {"values": [...]}
    * tags: dict or list of pairs

    When validation failed, we additionally repair a small set of known, local mismatches that would otherwise crash
    grouping, denormalization, or the event views. The goal is to keep tolerating near-miss payloads without spreading
    type-checks through the rest of the codebase.
    """
    if not isinstance(data, dict):
        return {}

    data = deepcopy(data)

    if "tags" in data and isinstance(data["tags"], list):
        data["tags"] = _normalize_mapping(data["tags"])

    if "exception" in data:
        data["exception"] = _normalize_values(data["exception"], _normalize_exception, validation_failed)

    if "threads" in data:
        data["threads"] = _normalize_values(data["threads"], _normalize_thread, validation_failed)

    if "breadcrumbs" in data:
        data["breadcrumbs"] = _normalize_values(data["breadcrumbs"], _normalize_breadcrumb, validation_failed)

    if not validation_failed:
        return data

    for key in [
        "platform",
        "level",
        "logger",
        "transaction",
        "server_name",
        "release",
        "dist",
        "environment",
    ]:
        if key in data:
            data[key] = _as_string(data[key])

    if "message" in data and not isinstance(data["message"], dict):
        data["message"] = _as_string(data["message"])

    if "logentry" in data and not isinstance(data["logentry"], dict):
        data["logentry"] = {"formatted": _as_string(data["logentry"])}

    if "request" in data:
        request = data["request"]
        if not isinstance(request, dict) and _is_scalar(request):
            request = {"url": _as_string(request)}

        request = _normalize_mapping(request)
        if "method" in request:
            request["method"] = _as_string(request["method"])
        if "url" in request:
            request["url"] = _as_string(request["url"])
        if "headers" in request:
            request["headers"] = _normalize_mapping(request.get("headers"))
        data["request"] = request

    if "sdk" in data:
        sdk = _normalize_mapping(data["sdk"])
        if "name" in sdk:
            sdk["name"] = _as_string(sdk["name"])
        if "version" in sdk:
            sdk["version"] = _as_string(sdk["version"])
        if "packages" in sdk:
            sdk["packages"] = _normalize_values(sdk.get("packages"), lambda value, _: _normalize_mapping(value), True)
        if "integrations" in sdk and not isinstance(sdk["integrations"], list):
            sdk["integrations"] = [_as_string(sdk["integrations"])]
        if "integrations" in sdk and isinstance(sdk["integrations"], list):
            sdk["integrations"] = [_as_string(item) for item in sdk["integrations"]]
        if "settings" in sdk:
            sdk["settings"] = _normalize_mapping(sdk.get("settings"))
        data["sdk"] = sdk

    for key in ["contexts", "extra", "user", "_meta"]:
        if key in data:
            data[key] = _normalize_mapping(data[key])

    if "fingerprint" in data:
        if isinstance(data["fingerprint"], (list, tuple)):
            data["fingerprint"] = [_as_string(item) for item in data["fingerprint"]]
        elif _is_scalar(data["fingerprint"]):
            data["fingerprint"] = [_as_string(data["fingerprint"])]
        else:
            data["fingerprint"] = []

    if "debug_meta" in data:
        debug_meta = _normalize_mapping(data["debug_meta"])
        if "images" in debug_meta:
            debug_meta["images"] = _normalize_values(
                debug_meta.get("images"), lambda value, _: _normalize_mapping(value), True)
        if "sdk_info" in debug_meta:
            debug_meta["sdk_info"] = _normalize_mapping(debug_meta.get("sdk_info"))
        data["debug_meta"] = debug_meta

    if "stacktrace" in data:
        data["stacktrace"] = _normalize_stacktrace(data["stacktrace"], True)

    return data
