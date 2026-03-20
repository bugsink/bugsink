from copy import deepcopy
import re


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


def normalize_event_data(data):
    """
    Canonicalize the few event-data interfaces for which Bugsink intentionally supports multiple incoming shapes.

    This mirrors the old view-layer knowledge such as issues.utils.get_values():
    * exception / threads / breadcrumbs may be a list or {"values": [...]}
    * tags may be a dict or a list of pairs

    The purpose here is not to "repair invalid events". It is only to give the rest of Bugsink a single internal shape
    for interfaces where we already knowingly accepted multiple shapes.
    """
    if not isinstance(data, dict):
        return {}

    data = deepcopy(data)

    if "tags" in data and isinstance(data["tags"], list):
        data["tags"] = _normalize_mapping(data["tags"])

    for key in ["exception", "threads", "breadcrumbs"]:
        if key not in data:
            continue

        value = data[key]
        if isinstance(value, dict):
            # The documented Sentry shape is {"values": [...]}, but in practice we also see a plain dict here. The old
            # get_values() helper already encoded the choice to wrap that plain dict, so we keep doing that centrally.
            data[key] = value.get("values", [value])
        elif isinstance(value, tuple):
            data[key] = list(value)

    return data


def _repair_string_field(data, key):
    if key not in data:
        return False

    # These fields are all optional scalar values that Bugsink ultimately stores in CharFields or uses as strings in
    # grouping / denormalized fields. If validation told us the field itself is wrong, coercing a scalar is the least
    # surprising repair; container values still collapse to "" to avoid leaking weird structures into those call-sites.
    data[key] = _as_string(data[key])
    return True


def _repair_message_field(data):
    if "message" not in data or isinstance(data["message"], dict):
        return False

    # Top-level "message" historically appears both as a dict and as a plain string. When validation points here and
    # we got a scalar, Bugsink's log-message code already knows how to use the string form.
    data["message"] = _as_string(data["message"])
    return True


def _repair_logentry_field(data):
    if "logentry" not in data or isinstance(data["logentry"], dict):
        return False

    # Our grouping/details code expects logentry to be the structured form. If validation explicitly complained about
    # logentry itself, we keep the scalar but move it into "formatted", which is the closest equivalent.
    data["logentry"] = {"formatted": _as_string(data["logentry"])}
    return True


def _repair_request_field(data):
    if "request" not in data:
        return False

    request = data["request"]
    if not isinstance(request, dict) and _is_scalar(request):
        # The request summary in the UI only needs method/url, and a scalar request has in practice meant "this is the
        # URL". We only do this when validation specifically points at request.
        request = {"url": _as_string(request)}

    request = _normalize_mapping(request)
    if "method" in request:
        request["method"] = _as_string(request["method"])
    if "url" in request:
        request["url"] = _as_string(request["url"])
    if "headers" in request:
        request["headers"] = _normalize_mapping(request.get("headers"))

    data["request"] = request
    return True


def _repair_sdk_field(data):
    if "sdk" not in data:
        return False

    sdk = _normalize_mapping(data["sdk"])

    if "name" in sdk:
        sdk["name"] = _as_string(sdk["name"])
    if "version" in sdk:
        sdk["version"] = _as_string(sdk["version"])

    if "packages" in sdk:
        packages = sdk["packages"]
        if isinstance(packages, dict):
            sdk["packages"] = [packages]
        elif isinstance(packages, tuple):
            sdk["packages"] = list(packages)
        elif not isinstance(packages, list):
            sdk["packages"] = []

    if "integrations" in sdk:
        integrations = sdk["integrations"]
        if isinstance(integrations, list):
            sdk["integrations"] = [_as_string(item) for item in integrations]
        elif _is_scalar(integrations):
            sdk["integrations"] = [_as_string(integrations)]
        else:
            sdk["integrations"] = []

    if "settings" in sdk:
        sdk["settings"] = _normalize_mapping(sdk["settings"])

    data["sdk"] = sdk
    return True


def _repair_mapping_field(data, key):
    if key not in data:
        return False

    # These are "arbitrary mapping" sections that our code reads with .get(). If validation singled one of them out,
    # we keep only the mapping-like part instead of letting a list/number/string blow up later.
    data[key] = _normalize_mapping(data[key])
    return True


def _repair_fingerprint_field(data):
    if "fingerprint" not in data:
        return False

    fingerprint = data["fingerprint"]
    if isinstance(fingerprint, (list, tuple)):
        data["fingerprint"] = [_as_string(item) for item in fingerprint]
    elif _is_scalar(fingerprint):
        data["fingerprint"] = [_as_string(fingerprint)]
    else:
        data["fingerprint"] = []

    return True


def _repair_stacktrace_field(data):
    if "stacktrace" not in data:
        return False

    stacktrace = _normalize_mapping(data["stacktrace"])
    if "frames" in stacktrace:
        stacktrace["frames"] = _normalize_frames(stacktrace["frames"])
    else:
        stacktrace["frames"] = []

    data["stacktrace"] = stacktrace
    return True


def _repair_sequence_interface(data, key):
    if key not in data:
        return False

    # exception / threads / breadcrumbs are the classic "two shapes" interfaces in the Sentry payload. When the
    # validator points at the interface itself, we reuse the same wrapping logic as in normalize_event_data(). When it
    # points deeper into the interface, the per-item repairs below take over.
    value = data[key]
    if isinstance(value, dict):
        data[key] = value.get("values", [value])
    elif isinstance(value, tuple):
        data[key] = list(value)
    elif not isinstance(value, list):
        data[key] = [value]

    return True


def _path_index(path, prefix):
    match = re.match(rf"^{re.escape(prefix)}\[(\d+)\]", path)
    if match is None:
        return None

    return int(match.group(1))


def _repair_exception_item(data, path):
    if "exception" not in data or not data["exception"]:
        return False

    index = _path_index(path, "$.exception")
    if index is None or index >= len(data["exception"]):
        return False

    exception = data["exception"][index]
    if not isinstance(exception, dict):
        data["exception"][index] = {"value": exception}
        return True

    if "mechanism" in exception:
        exception["mechanism"] = _normalize_mapping(exception["mechanism"])

    if "stacktrace" in exception:
        stacktrace = _normalize_mapping(exception["stacktrace"])
        if "frames" in stacktrace:
            stacktrace["frames"] = _normalize_frames(stacktrace["frames"])
        exception["stacktrace"] = stacktrace

    return True


def _repair_thread_item(data, path):
    if "threads" not in data or not data["threads"]:
        return False

    index = _path_index(path, "$.threads")
    if index is None or index >= len(data["threads"]):
        return False

    thread = data["threads"][index]
    if not isinstance(thread, dict):
        data["threads"][index] = {}
        return True

    if "stacktrace" in thread:
        stacktrace = _normalize_mapping(thread["stacktrace"])
        if "frames" in stacktrace:
            stacktrace["frames"] = _normalize_frames(stacktrace["frames"])
        thread["stacktrace"] = stacktrace

    return True


def _repair_breadcrumb_item(data, path):
    if "breadcrumbs" not in data or not data["breadcrumbs"]:
        return False

    index = _path_index(path, "$.breadcrumbs")
    if index is None or index >= len(data["breadcrumbs"]):
        return False

    breadcrumb = data["breadcrumbs"][index]
    if not isinstance(breadcrumb, dict):
        data["breadcrumbs"][index] = {"message": _as_string(breadcrumb)}
        return True

    if "data" in breadcrumb:
        breadcrumb["data"] = _normalize_mapping(breadcrumb["data"])

    return True


def repair_event_data(parsed_data, get_validation_problem):
    """
    Repair event data by following the validator's reported failing path.

    We validate, repair exactly the part that the validator complained about, and validate again. This keeps the repair
    logic narrow and explicit: no broad "validation failed, so normalize everything" fallback.
    """
    repaired_data = deepcopy(parsed_data)
    seen = set()

    while True:
        problem = get_validation_problem(repaired_data)
        if problem is None:
            return repaired_data

        signature = (problem.path, problem.message)
        if signature in seen:
            return repaired_data
        seen.add(signature)

        if not _repair_event_data_for_problem(repaired_data, problem.path):
            return repaired_data


def _repair_event_data_for_problem(data, path):
    repairers = [
        ("prefix", "$.exception[", lambda data: _repair_exception_item(data, path)),
        ("prefix", "$.threads[", lambda data: _repair_thread_item(data, path)),
        ("prefix", "$.breadcrumbs[", lambda data: _repair_breadcrumb_item(data, path)),
        ("exact", "$.platform", lambda data: _repair_string_field(data, "platform")),
        ("exact", "$.level", lambda data: _repair_string_field(data, "level")),
        ("exact", "$.logger", lambda data: _repair_string_field(data, "logger")),
        ("exact", "$.transaction", lambda data: _repair_string_field(data, "transaction")),
        ("exact", "$.server_name", lambda data: _repair_string_field(data, "server_name")),
        ("exact", "$.release", lambda data: _repair_string_field(data, "release")),
        ("exact", "$.dist", lambda data: _repair_string_field(data, "dist")),
        ("exact", "$.environment", lambda data: _repair_string_field(data, "environment")),
        ("exact", "$.message", _repair_message_field),
        ("exact", "$.logentry", _repair_logentry_field),
        ("prefix", "$.request", _repair_request_field),
        ("prefix", "$.sdk", _repair_sdk_field),
        ("prefix", "$.contexts", lambda data: _repair_mapping_field(data, "contexts")),
        ("prefix", "$.extra", lambda data: _repair_mapping_field(data, "extra")),
        ("prefix", "$.user", lambda data: _repair_mapping_field(data, "user")),
        ("prefix", "$._meta", lambda data: _repair_mapping_field(data, "_meta")),
        ("prefix", "$.debug_meta", lambda data: _repair_mapping_field(data, "debug_meta")),
        ("exact", "$.fingerprint", _repair_fingerprint_field),
        ("prefix", "$.stacktrace", _repair_stacktrace_field),
        ("exact", "$.exception", lambda data: _repair_sequence_interface(data, "exception")),
        ("exact", "$.threads", lambda data: _repair_sequence_interface(data, "threads")),
        ("exact", "$.breadcrumbs", lambda data: _repair_sequence_interface(data, "breadcrumbs")),
    ]

    for match_mode, prefix, repairer in repairers:
        if match_mode == "exact" and path == prefix:
            return repairer(data)

        if match_mode == "prefix" and path.startswith(prefix):
            return repairer(data)

    return False
