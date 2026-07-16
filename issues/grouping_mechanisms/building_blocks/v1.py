from sentry.at_glitchtip_af9a700a8706.stacktraces.processing import get_crash_location
from sentry.at_glitchtip_af9a700a8706.utils.safe import get_path, trim
from sentry.at_glitchtip_af9a700a8706.utils.strings import strip


# Copied from issues.utils because get_main_exception depends on it. Keeping the copy here means v1 grouping will not
# be inadvertently affected by future changes to the application-level event-shape helper.
def get_values(obj):
    if obj is None:
        return None

    if isinstance(obj, list):
        return obj

    if isinstance(obj, dict):
        if "values" not in obj:
            return [obj]

        return obj["values"]

    raise ValueError("Expected exception/threads/breadcrumbs to be a list or a dict, got %r" % obj)


def get_type_and_value_for_data(data):
    # note: this is a verbatim copy of the function in issues.utils, but we need to keep it here so that v1 grouping is
    # not affected by future changes to the application-level event-shape helper (its transitive dependency closure is
    # actually quite large so despite the fact that it seems like a straightforward data-getter the likelihood of it
    # being affected by future changes is high).
    if "exception" in data and data["exception"]:
        return get_exception_type_and_value_for_exception(data)
    return get_exception_type_and_value_for_logmessage(data)


def get_exception_type_and_value_for_logmessage(data):
    message = strip(
        get_path(data, "logentry", "message")
        or get_path(data, "logentry", "formatted")
        or get_path(data, "message", "message")
        or get_path(data, "message", "formatted")
    )

    if not message and isinstance(data.get("message"), str):
        message = data.get("message")

    if message:
        return "Log Message", message.splitlines()[0][:1024]

    return "Log Message", "<no log message>"


def get_main_exception(data):
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
    exception = get_main_exception(data)
    if exception is None:
        return "<unknown>", ""

    value = trim(get_path(exception, "value", default=""), 1024)

    if get_path(exception, "mechanism", "synthetic"):
        _, function = get_crash_location(data)
        if function:
            return function, ""
        return "<unknown>", ""

    type_ = trim(get_path(exception, "type", default="Error"), 128)

    return type_, value


def get_title_for_exception_type_and_value(type_, value):
    if not value:
        return type_

    if not isinstance(value, str):
        value = str(value)

    return "{}: {}".format(type_, value.splitlines()[0])
