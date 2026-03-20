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


def _normalize_stacktrace(value):
    stacktrace = _normalize_mapping(value)
    if not stacktrace:
        return {}

    stacktrace["frames"] = _normalize_frames(stacktrace.get("frames"))
    return stacktrace


def _normalize_exception(value):
    if isinstance(value, dict):
        value = deepcopy(value)
        value["mechanism"] = _normalize_mapping(value.get("mechanism"))
        value["stacktrace"] = _normalize_stacktrace(value.get("stacktrace"))
        return value

    if _is_scalar(value):
        return {"value": value}

    return {}


def _normalize_thread(value):
    if not isinstance(value, dict):
        return {}

    value = deepcopy(value)
    value["stacktrace"] = _normalize_stacktrace(value.get("stacktrace"))
    return value


def _normalize_breadcrumb(value):
    if isinstance(value, dict):
        value = deepcopy(value)
        value["data"] = _normalize_mapping(value.get("data"))
        return value

    if _is_scalar(value):
        return {"message": _as_string(value)}

    return {}


def _normalize_values(value, item_normalizer):
    if value is None:
        return []

    if isinstance(value, dict):
        if "values" in value:
            value = value["values"]
        else:
            value = [value]

    if isinstance(value, tuple):
        value = list(value)

    if not isinstance(value, list):
        value = [value]

    return [item_normalizer(item) for item in value]


def normalize_event_data(data):
    if not isinstance(data, dict):
        return {}

    data = deepcopy(data)

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
        for key in ["method", "url"]:
            if key in request:
                request[key] = _as_string(request[key])
        request["headers"] = _normalize_mapping(request.get("headers"))
        data["request"] = request

    if "sdk" in data:
        sdk = _normalize_mapping(data["sdk"])
        for key in ["name", "version"]:
            if key in sdk:
                sdk[key] = _as_string(sdk[key])
        sdk["packages"] = _normalize_values(sdk.get("packages"), _normalize_mapping)
        sdk["integrations"] = [_as_string(item) for item in sdk.get("integrations", [])] \
            if isinstance(sdk.get("integrations"), list) else []
        sdk["settings"] = _normalize_mapping(sdk.get("settings"))
        data["sdk"] = sdk

    for key in ["contexts", "extra", "user", "_meta"]:
        if key in data:
            data[key] = _normalize_mapping(data[key])

    if "tags" in data:
        data["tags"] = _normalize_mapping(data["tags"])

    if "fingerprint" in data:
        if isinstance(data["fingerprint"], (list, tuple)):
            data["fingerprint"] = [_as_string(item) for item in data["fingerprint"]]
        elif _is_scalar(data["fingerprint"]):
            data["fingerprint"] = [_as_string(data["fingerprint"])]
        else:
            data["fingerprint"] = []

    if "debug_meta" in data:
        debug_meta = _normalize_mapping(data["debug_meta"])
        debug_meta["images"] = _normalize_values(debug_meta.get("images"), _normalize_mapping)
        debug_meta["sdk_info"] = _normalize_mapping(debug_meta.get("sdk_info"))
        data["debug_meta"] = debug_meta

    if "stacktrace" in data:
        data["stacktrace"] = _normalize_stacktrace(data["stacktrace"])

    if "exception" in data:
        data["exception"] = _normalize_values(data["exception"], _normalize_exception)

    if "threads" in data:
        data["threads"] = _normalize_values(data["threads"], _normalize_thread)

    if "breadcrumbs" in data:
        data["breadcrumbs"] = _normalize_values(data["breadcrumbs"], _normalize_breadcrumb)

    return data
