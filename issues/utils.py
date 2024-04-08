from django.utils.encoding import force_str

from sentry.stacktraces.functions import get_function_name_for_frame
from sentry.stacktraces.processing import get_crash_frame_from_event_data
from sentry.utils.safe import get_path, trim

from sentry.utils.strings import strip


def get_type_and_value_for_data(data):
    if "exception" in data and data["exception"]:
        return get_exception_type_and_value_for_exception(data)
    return get_exception_type_and_value_for_logmessage(data)


def get_exception_type_and_value_for_logmessage(data):
    message = strip(
        get_path(data, "logentry", "message")
        or get_path(data, "logentry", "formatted")
    )

    if message:
        return "Log Message", message.splitlines()[0]

    return "Log Message", "<no log message>"


def get_crash_location(data):
    frame = get_crash_frame_from_event_data(
        data,
        frame_filter=lambda x: x.get("function") not in (None, "<redacted>", "<unknown>"),
    )
    if frame is not None:
        func = get_function_name_for_frame(frame, data.get("platform"))
        return frame.get("filename") or frame.get("abs_path"), func
    return None, None


def get_exception_type_and_value_for_exception(data):
    if isinstance(data.get("exception"), list):
        if len(data["exception"]) == 0:
            return "<unknown>", ""

    exception = get_path(data, "exception", "values", -1)
    if not exception:
        return "<unknown>", ""

    value = trim(get_path(exception, "value", default=""), 1024)

    # From the sentry docs:
    # > An optional flag indicating that this error is synthetic. Synthetic errors are errors that carry little
    # > meaning by themselves.
    # If this flag is set, we ignored the Exception's type and used the function name instead (if available).
    if get_path(exception, "mechanism", "synthetic"):
        _, function = get_crash_location(data)
        if function:
            return function, ""
        return "<unknown>", ""

    type_ = trim(get_path(exception, "type", default="Error"), 128)

    return type_, value


def default_issue_grouper(calculated_type, calculated_value, transaction):
    title = get_title_for_exception_type_and_value(calculated_type, calculated_value)
    return title + " ⋄ " + transaction


def get_issue_grouper_for_data(data, calculated_type=None, calculated_value=None):
    if calculated_type is None and calculated_value is None:
        # convenience for calling code from tests, when digesting we don't do this because we already have this info
        calculated_type, calculated_value = get_type_and_value_for_data(data)

    transaction = force_str(data.get("transaction") or "<no transaction>")
    fingerprint = data.get("fingerprint")

    if fingerprint:
        return " ⋄ ".join([
            default_issue_grouper(calculated_type, calculated_value, transaction) if part == "{{ default }}" else part
            for part in fingerprint
        ])

    return default_issue_grouper(calculated_type, calculated_value, transaction)


def get_title_for_exception_type_and_value(type_, value):
    if not value:
        return type_

    if not isinstance(value, str):
        value = str(value)

    return "{}: {}".format(type_, value.splitlines()[0])


# utilities related to storing and retrieving release-versions; we use the fact that sentry (and we've adopted their
# limitation) disallows the use of newlines in release-versions, so we can use newlines as a separator

def parse_lines(s):
    # Remove the last element, which is an empty string because of the trailing newline (\n as terminator not separator)
    return s.split("\n")[:-1]


def serialize_lines(l):
    return "".join([e + "\n" for e in l])


def filter_qs_for_fixed_at(qs, release):
    return qs.filter(fixed_at__contains=release + "\n")


def exclude_qs_for_fixed_at(qs, release):
    return qs.exclude(fixed_at__contains=release + "\n")
