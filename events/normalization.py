import copy


VALUES_INTERFACE_KEYS = {"exception", "threads", "breadcrumbs"}

STRING_PATHS = {
    ("platform",),
    ("level",),
    ("logger",),
    ("transaction",),
    ("server_name",),
    ("release",),
    ("dist",),
    ("environment",),
    ("user", "id"),
    ("sdk", "name"),
    ("sdk", "version"),
    ("request", "method"),
    ("request", "url"),
}


def normalize_event_data(parsed_data):
    # This is intentionally not a "repair anything" pass. By the time we get here, the data is either already valid or
    # has just been repaired in response to a concrete validation failure. The job here is only to pick a single,
    # spec-shaped representation for the interfaces where Bugsink knowingly accepts more than one layout.
    normalized_data = copy.deepcopy(parsed_data)

    for key in VALUES_INTERFACE_KEYS:
        _normalize_values_interface(normalized_data, key)

    for exception in _iter_values_interface(normalized_data.get("exception")):
        _normalize_stacktrace_frames(exception)

    for thread in _iter_values_interface(normalized_data.get("threads")):
        _normalize_stacktrace_frames(thread)

    return normalized_data


def repair_event_data(parsed_data, get_validation_problem):
    # Validation stays the source of truth: we keep asking the validator for the next concrete problem and only apply a
    # repair when we have an explicit rule for that exact kind of failure.
    repaired = copy.deepcopy(parsed_data)
    seen = set()

    while True:
        problem = get_validation_problem(repaired)
        if problem is None:
            return repaired

        signature = (problem.absolute_path, problem.validator, problem.message)
        if signature in seen:
            return repaired
        seen.add(signature)

        if not _repair_for_problem(repaired, problem):
            return repaired


def _repair_for_problem(parsed_data, problem):
    if _repair_values_interface(parsed_data, problem):
        return True

    if _repair_top_level_message(parsed_data, problem):
        return True

    if _repair_logentry(parsed_data, problem):
        return True

    if _repair_request(parsed_data, problem):
        return True

    if _repair_scalar_string_field(parsed_data, problem):
        return True

    if _repair_request_header(parsed_data, problem):
        return True

    if _repair_fingerprint_value(parsed_data, problem):
        return True

    if _repair_stacktrace(parsed_data, problem):
        return True

    if _repair_frame(parsed_data, problem):
        return True

    return False


def _repair_values_interface(parsed_data, problem):
    if len(problem.absolute_path) != 1 or problem.absolute_path[0] not in VALUES_INTERFACE_KEYS:
        return False

    # Exception, threads, and breadcrumbs are the three places where SDKs most often send "almost right" container
    # shapes: a flat list instead of {"values": [...]}, or a single dict that should have been wrapped.
    value = parsed_data.get(problem.absolute_path[0])

    if isinstance(value, list):
        parsed_data[problem.absolute_path[0]] = {"values": value}
        return True

    if isinstance(value, tuple):
        parsed_data[problem.absolute_path[0]] = {"values": list(value)}
        return True

    if isinstance(value, dict) and "values" not in value:
        # Some SDKs send a single exception/thread/breadcrumb object directly instead of wrapping it in {"values": ...}.
        parsed_data[problem.absolute_path[0]] = {"values": [value]}
        return True

    return False


def _repair_top_level_message(parsed_data, problem):
    if problem.validator != "additionalProperties" or problem.absolute_path != ():
        return False

    unexpected = _get_unexpected_keys(problem)
    if "message" not in unexpected or "message" not in parsed_data:
        return False

    # Some SDKs still use the deprecated top-level "message". Bugsink's display and grouping logic works from logentry,
    # so the repair is to move the data into that modern shape instead of teaching the rest of the code two locations.
    message_value = parsed_data.pop("message")

    logentry = parsed_data.get("logentry")
    if isinstance(logentry, str):
        logentry = parsed_data["logentry"] = {"formatted": logentry}

    if message_value is None:
        return True

    if isinstance(message_value, str):
        if logentry is None:
            parsed_data["logentry"] = {"formatted": message_value}
            return True

        if isinstance(logentry, dict) and "formatted" not in logentry:
            logentry["formatted"] = message_value
            return True

        return False

    if not isinstance(message_value, dict):
        return False

    if logentry is None:
        parsed_data["logentry"] = message_value
        return True

    if not isinstance(logentry, dict):
        return False

    for key in ["formatted", "message", "params"]:
        if key in message_value and key not in logentry:
            logentry[key] = message_value[key]

    return True


def _repair_logentry(parsed_data, problem):
    if problem.validator != "type" or problem.absolute_path != ("logentry",):
        return False

    if not isinstance(parsed_data.get("logentry"), str):
        return False

    parsed_data["logentry"] = {"formatted": parsed_data["logentry"]}
    return True


def _repair_request(parsed_data, problem):
    if problem.validator != "type" or problem.absolute_path != ("request",):
        return False

    if not isinstance(parsed_data.get("request"), str):
        return False

    # A bare request string is not spec-shaped, but in practice it is almost always just the URL.
    parsed_data["request"] = {"url": parsed_data["request"]}
    return True


def _repair_scalar_string_field(parsed_data, problem):
    if problem.validator != "type" or problem.absolute_path not in STRING_PATHS:
        return False

    # These fields all end up in CharFields, grouping, tags, or otherwise text-oriented display. When an SDK sends a
    # scalar in the wrong JSON type, preserving the value as text is the least surprising repair.
    parent, key = _get_parent_and_key(parsed_data, problem.absolute_path)
    if parent is None or not _has_item(parent, key):
        return False

    value = _get_item(parent, key)
    string_value = _coerce_scalar_to_string(value)
    if string_value is None:
        return False

    _set_item(parent, key, string_value)
    return True


def _repair_request_header(parsed_data, problem):
    if problem.validator != "type" or len(problem.absolute_path) != 3:
        return False

    if tuple(problem.absolute_path[:2]) != ("request", "headers"):
        return False

    headers = parsed_data.get("request", {}).get("headers")
    header_name = problem.absolute_path[2]

    if not isinstance(headers, dict) or header_name not in headers:
        return False

    # ASP.NET style payloads have shown up with one-element header lists, and some broken payloads send numeric header
    # values. For Bugsink's display and UA parsing, the meaningful normalized shape is a regular header string.
    value = headers[header_name]
    if isinstance(value, (list, tuple)):
        parts = []
        for part in value:
            string_part = _coerce_scalar_to_string(part)
            if string_part is None:
                return False
            parts.append(string_part)

        headers[header_name] = ", ".join(parts)
        return True

    string_value = _coerce_scalar_to_string(value)
    if string_value is None:
        return False

    headers[header_name] = string_value
    return True


def _repair_fingerprint_value(parsed_data, problem):
    if problem.validator != "type" or len(problem.absolute_path) != 2:
        return False

    if problem.absolute_path[0] != "fingerprint" or not isinstance(problem.absolute_path[1], int):
        return False

    fingerprint = parsed_data.get("fingerprint")
    index = problem.absolute_path[1]

    if not isinstance(fingerprint, list) or index >= len(fingerprint):
        return False

    # Fingerprint parts are joined into grouping keys, so a numeric fragment should behave like its string form.
    string_value = _coerce_scalar_to_string(fingerprint[index])
    if string_value is None:
        return False

    fingerprint[index] = string_value
    return True


def _repair_stacktrace(parsed_data, problem):
    if problem.absolute_path[-1:] != ("stacktrace",):
        return False

    stacktrace = _get_at_path(parsed_data, problem.absolute_path)
    if not isinstance(stacktrace, dict):
        return False

    if problem.validator == "required" and "frames" in (problem.validator_value or []):
        # Bugsink's stacktrace rendering can handle an empty frame list just fine; the broken sample here is "the SDK
        # clearly meant to send a stacktrace object, but forgot the frames container".
        stacktrace["frames"] = []
        return True

    return False


def _repair_frame(parsed_data, problem):
    if problem.validator == "type" and problem.absolute_path[-2:] == ("stacktrace", "frames"):
        frames = _get_at_path(parsed_data, problem.absolute_path)
        # Broken stacktraces have shown up with a single frame object or tuple where the schema wants a list.
        if isinstance(frames, tuple):
            _set_at_path(parsed_data, problem.absolute_path, list(frames))
            return True

        if isinstance(frames, dict):
            _set_at_path(parsed_data, problem.absolute_path, [frames])
            return True

        return False

    if problem.validator != "additionalProperties" or not _is_frame_problem(problem):
        return False

    frame = _get_at_path(parsed_data, problem.absolute_path)
    if not isinstance(frame, dict):
        return False

    repaired = False
    for key in _get_unexpected_keys(problem):
        # We don't use frame-only extras like "native" in grouping or rendering. Dropping the unknown keys gets us back
        # to the upstream frame shape while keeping the fields Bugsink does care about.
        if key in frame:
            del frame[key]
            repaired = True

    return repaired


def _normalize_values_interface(parsed_data, key):
    value = parsed_data.get(key)

    if isinstance(value, list):
        # The normalized shape for these interfaces is always the spec-shaped {"values": [...]} container.
        parsed_data[key] = {"values": value}
        return

    if isinstance(value, tuple):
        parsed_data[key] = {"values": list(value)}
        return

    if isinstance(value, dict) and isinstance(value.get("values"), tuple):
        value["values"] = list(value["values"])


def _normalize_stacktrace_frames(item):
    if not isinstance(item, dict):
        return

    stacktrace = item.get("stacktrace")
    if not isinstance(stacktrace, dict):
        return

    frames = stacktrace.get("frames")
    if isinstance(frames, tuple):
        stacktrace["frames"] = list(frames)
    elif isinstance(frames, dict):
        stacktrace["frames"] = [frames]


def _iter_values_interface(value):
    if not isinstance(value, dict):
        return []

    values = value.get("values")
    if not isinstance(values, list):
        return []

    return values


def _coerce_scalar_to_string(value):
    if isinstance(value, bool):
        return str(value).lower()

    if isinstance(value, (int, float, str)):
        return str(value)

    return None


def _get_unexpected_keys(problem):
    if problem.validator != "additionalProperties":
        return []

    if not isinstance(problem.instance, dict) or not isinstance(problem.schema, dict):
        return []

    properties = set(problem.schema.get("properties", {}))
    return [key for key in problem.instance if key not in properties]


def _is_frame_problem(problem):
    path = problem.absolute_path
    return len(path) >= 3 and path[-2] == "frames" and isinstance(path[-1], int) and path[-3] == "stacktrace"


def _get_at_path(obj, path):
    current = obj

    for part in path:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
            continue

        if isinstance(current, list):
            if not isinstance(part, int) or not (0 <= part < len(current)):
                return None
            current = current[part]
            continue

        return None

    return current


def _set_at_path(obj, path, value):
    parent, key = _get_parent_and_key(obj, path)
    if parent is None:
        return False

    _set_item(parent, key, value)
    return True


def _get_parent_and_key(obj, path):
    if not path:
        return None, None

    current = obj
    for part in path[:-1]:
        if isinstance(current, dict):
            if part not in current:
                return None, None
            current = current[part]
            continue

        if isinstance(current, list):
            if not isinstance(part, int) or not (0 <= part < len(current)):
                return None, None
            current = current[part]
            continue

        return None, None

    return current, path[-1]


def _has_item(parent, key):
    if isinstance(parent, dict):
        return key in parent

    if isinstance(parent, list):
        return isinstance(key, int) and 0 <= key < len(parent)

    return False


def _get_item(parent, key):
    if isinstance(parent, dict):
        return parent[key]

    return parent[key]


def _set_item(parent, key, value):
    parent[key] = value
