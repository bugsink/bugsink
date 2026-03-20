import copy
import re


_PATH_TOKEN_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


def normalize_event_data(parsed_data):
    normalized = copy.deepcopy(parsed_data)

    # The validator accepts both the documented {"values": [...]} shape and the flat-list shape for these interfaces.
    # Internally we always use the flat-list shape so that grouping and the views only have one shape to think about.
    for key in ["exception", "threads", "breadcrumbs"]:
        if key in normalized:
            normalized[key] = _normalize_values_interface(normalized[key])

    for exception in normalized.get("exception") or []:
        _normalize_stacktrace_frames(exception)

    for thread in normalized.get("threads") or []:
        _normalize_stacktrace_frames(thread)

    if isinstance(normalized.get("tags"), list):
        normalized["tags"] = {
            str(key): value
            for key, value in normalized["tags"]
            if isinstance(key, str)
        }

    return normalized


def repair_event_data(parsed_data, get_validation_problem):
    repaired = copy.deepcopy(parsed_data)
    seen = set()

    while True:
        problem = get_validation_problem(repaired)
        if problem is None:
            return repaired

        signature = (problem.path, problem.message)
        if signature in seen:
            return repaired
        seen.add(signature)

        if not _repair_for_problem(repaired, problem):
            return repaired


def _normalize_values_interface(value):
    if value is None:
        return None

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, dict):
        if "values" in value:
            values = value["values"]
            if values is None:
                return []
            if isinstance(values, tuple):
                return list(values)
            return values

        # Seen with sentry-roblox style payloads: a plain dict where the interface should have been wrapped.
        return [value]

    return value


def _normalize_stacktrace_frames(item):
    stacktrace = item.get("stacktrace")
    if not isinstance(stacktrace, dict):
        return

    frames = stacktrace.get("frames")
    if frames is None:
        stacktrace["frames"] = []
    elif isinstance(frames, tuple):
        stacktrace["frames"] = list(frames)
    elif isinstance(frames, dict):
        stacktrace["frames"] = [frames]


def _repair_for_problem(parsed_data, problem):
    if problem.path == "$" and _repair_top_level_message(parsed_data, problem.message):
        return True

    if problem.path in ["$.exception", "$.threads", "$.breadcrumbs"]:
        # Bugsink has long treated these three interfaces as "the same kind of annoyance": SDKs may send the wrapped
        # {"values": [...]} shape, the flat-list shape, or occasionally a plain dict. Internally we normalize them to
        # the flat-list shape so the rest of the code only has to handle one layout.
        return _repair_values_interface(parsed_data, problem.path[2:])

    if problem.path == "$.logentry":
        return _repair_logentry(parsed_data)

    if problem.path == "$.request":
        return _repair_request(parsed_data)

    if problem.path == "$.tags":
        return _repair_tags(parsed_data)

    if problem.path == "$.user.id":
        # User ids end up in tags and the UI as text. An integer user id is therefore not semantically wrong for
        # Bugsink; it just needs to be moved into the string-only shape that the schema wants.
        return _repair_scalar_string_field(parsed_data, "user", "id")

    if problem.path in [
        "$.platform",
        "$.level",
        "$.logger",
        "$.transaction",
        "$.server_name",
        "$.release",
        "$.dist",
        "$.environment",
    ]:
        # These fields all feed into CharFields, grouping, titles, or tags. A scalar in the wrong JSON type is still
        # meaningful data to Bugsink, so we coerce it the same way the rest of the codebase already implicitly expects.
        return _repair_scalar_string_field(parsed_data, problem.path[2:])

    if problem.path in ["$.sdk.name", "$.sdk.version"]:
        return _repair_scalar_string_field(parsed_data, "sdk", problem.path.split(".")[-1])

    if problem.path in ["$.request.method", "$.request.url"]:
        return _repair_scalar_string_field(parsed_data, "request", problem.path.split(".")[-1])

    if problem.path.startswith("$.request.headers."):
        # ASP.NET style payloads sometimes send header values as one-element lists. For Bugsink's request display and
        # UA parsing, the meaningful shape is a regular header string.
        return _repair_request_header(parsed_data, problem.path.rsplit(".", 1)[-1])

    if problem.path.startswith("$.fingerprint["):
        # Fingerprints are eventually joined into the grouping key; a numeric fragment should therefore behave the same
        # as its string representation instead of killing ingestion.
        return _repair_fingerprint_value(parsed_data, problem.path)

    if problem.path.endswith(".stacktrace"):
        return _repair_stacktrace(problem.path, parsed_data, problem.message)

    if ".stacktrace.frames[" in problem.path:
        return _repair_frame(problem.path, parsed_data, problem.message)

    return False


def _repair_top_level_message(parsed_data, message):
    if "'message' was unexpected" not in message or "message" not in parsed_data:
        return False

    message_value = parsed_data.pop("message")

    # Some SDKs still put their log message in the deprecated top-level "message" field. Internally we want the
    # modern "logentry" shape so that details/grouping only need to look in one place.
    if isinstance(message_value, dict):
        if "logentry" not in parsed_data:
            parsed_data["logentry"] = message_value
            return True

        if isinstance(parsed_data["logentry"], dict):
            for key in ["message", "formatted", "params"]:
                if key not in parsed_data["logentry"] and key in message_value:
                    parsed_data["logentry"][key] = message_value[key]
            return True

        return False

    if isinstance(message_value, str):
        if "logentry" not in parsed_data:
            parsed_data["logentry"] = {"formatted": message_value}
            return True

        if isinstance(parsed_data["logentry"], dict) and "formatted" not in parsed_data["logentry"]:
            parsed_data["logentry"]["formatted"] = message_value
            return True

    return False


def _repair_values_interface(parsed_data, key):
    value = parsed_data.get(key)

    if isinstance(value, tuple):
        parsed_data[key] = list(value)
        return True

    if isinstance(value, list):
        return False

    if isinstance(value, dict):
        parsed_data[key] = _normalize_values_interface(value)
        return True

    return False


def _repair_logentry(parsed_data):
    if not isinstance(parsed_data.get("logentry"), str):
        return False

    # We already know from the validation error that a string is not a valid logentry object. For display/grouping the
    # formatted message is the closest fit.
    parsed_data["logentry"] = {"formatted": parsed_data["logentry"]}
    return True


def _repair_request(parsed_data):
    request = parsed_data.get("request")
    if isinstance(request, str):
        parsed_data["request"] = {"url": request}
        return True
    return False


def _repair_tags(parsed_data):
    tags = parsed_data.get("tags")
    if not isinstance(tags, list):
        return False

    repaired = {}
    for item in tags:
        if not isinstance(item, (list, tuple)) or len(item) != 2 or not isinstance(item[0], str):
            return False
        repaired[item[0]] = item[1]

    parsed_data["tags"] = repaired
    return True


def _repair_scalar_string_field(parsed_data, *path):
    parent, key = _get_parent_and_key(parsed_data, path)
    if parent is None or key not in parent:
        return False

    value = parent[key]
    if isinstance(value, bool):
        parent[key] = str(value).lower()
        return True

    if isinstance(value, (int, float, str)):
        parent[key] = str(value)
        return True

    return False


def _repair_request_header(parsed_data, header_name):
    headers = parsed_data.get("request", {}).get("headers")
    if not isinstance(headers, dict) or header_name not in headers:
        return False

    value = headers[header_name]
    if isinstance(value, list):
        headers[header_name] = ", ".join(str(item) for item in value)
        return True

    return False


def _repair_fingerprint_value(parsed_data, path):
    fingerprint = parsed_data.get("fingerprint")
    if not isinstance(fingerprint, list):
        return False

    match = re.match(r"^\$\.fingerprint\[(\d+)\]$", path)
    if match is None:
        return False

    index = int(match.group(1))
    if index >= len(fingerprint):
        return False

    value = fingerprint[index]
    if isinstance(value, bool):
        fingerprint[index] = str(value).lower()
        return True

    if isinstance(value, (int, float, str)):
        fingerprint[index] = str(value)
        return True

    return False


def _repair_stacktrace(path, parsed_data, message):
    if "'frames' is a required property" not in message:
        return False

    stacktrace = _get_at_json_path(parsed_data, path)
    if not isinstance(stacktrace, dict):
        return False

    # Bugsink's stacktrace rendering is perfectly happy with an empty frame list; this is the clean internal shape for
    # the "stacktrace object exists, but the SDK did not provide frames" cases in KNOWN-BROKEN.
    stacktrace["frames"] = []
    return True


def _repair_frame(path, parsed_data, message):
    frame = _get_at_json_path(parsed_data, path)
    if not isinstance(frame, dict):
        return False

    unexpected = re.findall(r"'([^']+)'", message)
    if not unexpected:
        return False

    repaired = False
    for key in unexpected:
        # We don't use extra frame attributes like "native" in grouping or the views; dropping them gets us back to
        # the schema-conforming frame shape without losing information Bugsink depends on.
        if key in frame:
            del frame[key]
            repaired = True

    return repaired


def _get_at_json_path(obj, path):
    current = obj
    for key, index in _PATH_TOKEN_RE.findall(path):
        current = current[key] if key else current[int(index)]
    return current


def _get_parent_and_key(obj, path):
    current = obj
    for key in path[:-1]:
        if not isinstance(current, dict) or key not in current:
            return None, None
        current = current[key]

    if not isinstance(current, dict):
        return None, None

    return current, path[-1]
