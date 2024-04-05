from sentry.stacktraces.functions import get_function_name_for_frame
from sentry.stacktraces.processing import get_crash_frame_from_event_data
from sentry.utils.safe import get_path, trim, truncatechars


def get_crash_location(data):
    frame = get_crash_frame_from_event_data(
        data,
        frame_filter=lambda x: x.get("function") not in (None, "<redacted>", "<unknown>"),
    )
    if frame is not None:
        func = get_function_name_for_frame(frame, data.get("platform"))
        return frame.get("filename") or frame.get("abs_path"), func
    return None, None


class ErrorEvent:

    def get_title(self, data):
        if isinstance(data.get("exception"), list):
            if len(data["exception"]) == 0:
                return "<unknown>"

        exception = get_path(data, "exception", "values", -1)
        if not exception:
            return "<unknown>"

        value = trim(get_path(exception, "value", default=""), 1024)

        # From the sentry docs:
        # > An optional flag indicating that this error is synthetic. Synthetic errors are errors that carry little
        # > meaning by themselves.
        # If this flag is set, we ignored the Exception's type and used the function name instead (if available).
        if get_path(exception, "mechanism", "synthetic"):
            _, function = get_crash_location(data)
            if function:
                return function
            return "<unknown>"

        type_ = trim(get_path(exception, "type", default="Error"), 128)

        if not value:
            return type_

        if not isinstance(value, str):
            value = str(value)

        return "{}: {}".format(type_, truncatechars(value.splitlines()[0]))
