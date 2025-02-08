from django.utils.encoding import force_str

from sentry.stacktraces.functions import get_function_name_for_frame
from sentry.stacktraces.processing import get_crash_frame_from_event_data, get_crash_location
from sentry.utils.safe import get_path, trim

from sentry.utils.strings import strip


def maybe_empty(s):
    return "" if not s else s


def get_values(obj):
    """
    https://develop.sentry.dev/sdk/data-model/event-payloads/exception/

    > The exception attribute should be an object with the attribute values containing a list of one or more values that
    > are objects in the format described below. Alternatively, the exception attribute may be a flat list of objects in
    > the format below.

    Same for threads & breadcrumbs:
    * https://develop.sentry.dev/sdk/data-model/event-payloads/threads/
    * https://develop.sentry.dev/sdk/data-model/event-payloads/breadcrumbs/

    This function gets that list, whether the exception already was it, or whether it was wrapped in a dict as the
    single value of a "values" key.
    """
    if obj is None:
        # None in None out allows us to compose this function with get_path (which returns None if any key is missing).
        return None

    if isinstance(obj, list):
        return obj

    if isinstance(obj, dict):
        if "values" not in obj:
            # This covers the case where the exception is neither of the above-documented formats, but is instead just a
            # plain dict. In that case, we wrap-with-list to get back into the documented format. Whether this is a
            # robust-enough solution is an open question. Seen for https://github.com/devSparkle/sentry-roblox
            # (Despite the fact that such formats are not up-to-spec, January 2025 Sentry still accepts them, so we
            # leave this funny workaround in place.)
            return [obj]

        return obj["values"]

    raise ValueError("Expected exception/threads/breadcrumbs to be a list or a dict, got %r" % obj)


def get_type_and_value_for_data(data):
    if "exception" in data and data["exception"]:
        return get_exception_type_and_value_for_exception(data)
    return get_exception_type_and_value_for_logmessage(data)


def get_exception_type_and_value_for_logmessage(data):
    """In Sentry's data-model, log messages are retrofitted into the event model; personally I'm not a fan of using an
    Error Tracking tool for logging, but we at least make sure to show meaningful titles for log messages. The Bugsink
    choice is: just use "Log Message" as the type, which at least clarifies what you're looking at"""

    message = strip(
        get_path(data, "logentry", "message")
        or get_path(data, "logentry", "formatted")
    )

    if message:
        return "Log Message", message.splitlines()[0][:1024]

    return "Log Message", "<no log message>"


def get_main_exception(data):
    """
    Gets the 'main exception' from exception-data, which Bugsink has defined to be the last exception in the chain,
    because it's the one you're most likely to care about. Why? I'd roughly distinguish 2 cases for reraising:

    1. intentionally rephrasing/retyping exceptions to more clearly express their meaning. In that case you
       certainly care more about the rephrased thing than the original, that's the whole point.

    2. actual "accidents" happening while error-handling. In that case you care about the accident first (bugsink
       is a system to help you think about cases that you didn't properly think about in the first place),
       although you may also care about the root cause. (In fact, sometimes you care more about the root cause,
       but I'd say you'll have to yak-shave your way there).

    For a contrasting viewpoint, see https://github.com/getsentry/sentry-javascript/issues/10851 (esp. in view of
    grouped exceptions, which we do not support)
    """
    if isinstance(data.get("exception"), list):
        if len(data["exception"]) == 0:
            return None

    values = get_values(get_path(data, "exception"))
    if values is None or len(values) == 0:
        return None

    exception = values[-1]
    if not exception:
        return None

    return exception


def get_exception_type_and_value_for_exception(data):
    """Extracts the type and value of the exception from the event data. The non-trivial part is that we have to handle
    multiple exceptions in a chain, missing values, and synthetic exceptions."""
    exception = get_main_exception(data)
    if exception is None:
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
    # This is the "default" issue grouper, both in the sense that it's the issue-grouper that's used for the part of the
    # fingerprint named "{{ default }}" and in the sense that it's the default issue grouper when no fingerprint is
    # provided. It's a simple issue grouper that concatenates the title and the transaction.

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
    # This is a simple function that formats the type and value of an exception in a way that's suitable for use as a
    # title. It's used in grouping, but also to actually display the title of an issue in the UI.

    if not value:
        return type_

    if not isinstance(value, str):
        value = str(value)

    return "{}: {}".format(type_, value.splitlines()[0])


def get_denormalized_fields_for_data(parsed_data):
    """Extracts some fields from the event data that are set "denormalized" (cached) on the issue model."""

    last_frame = get_crash_frame_from_event_data(parsed_data) or {}

    module = maybe_empty(last_frame.get("module", ""))
    function = maybe_empty(get_function_name_for_frame(last_frame, parsed_data.get("platform")))
    filename = maybe_empty(last_frame.get("filename", ""))

    return {
        "transaction": maybe_empty(parsed_data.get("transaction", ""))[:200],
        "last_frame_filename": filename[:255],
        "last_frame_module": module[:255],
        "last_frame_function": function[:255],
    }


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
