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

    def _get_summary(self, data):
        """Fetches some key info from the event data that is used as an input in title-generation and returns this as
        a dict of possible keys: "type", "value", "function"."""

        if isinstance(data.get("exception"), list):
            if len(data["exception"]) == 0:
                return {}

        exception = get_path(data, "exception", "values", -1)
        if not exception:
            return {}

        rv = {"value": trim(get_path(exception, "value", default=""), 1024)}

        # If the exception mechanism indicates a synthetic exception we do not want to record the type and value into
        # the summary.
        if not get_path(exception, "mechanism", "synthetic"):
            rv["type"] = trim(get_path(exception, "type", default="Error"), 128)

        # Attach crash location if available
        _, function = get_crash_location(data)
        if function:
            rv["function"] = function

        return rv

    def get_title(self, data):
        summary = self._get_summary(data)

        type_ = summary.get("type")

        if type_ is None:
            return summary.get("function") or "<unknown>"

        if not summary.get("value"):
            return type_

        if not isinstance(summary["value"], str):
            summary["value"] = str(summary["value"])

        return "{}: {}".format(type_, truncatechars(summary["value"].splitlines()[0]))
