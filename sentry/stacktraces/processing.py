from sentry.stacktraces.functions import get_function_name_for_frame
from sentry.utils.safe import get_path


def get_crash_frame_from_event_data(data, frame_filter=None):
    from issues.utils import get_values  # changed by Bugsink
    values = get_values(get_path(data, "exception"))

    frames = get_path(
        values, -1, "stacktrace", "frames"
    ) or get_path(data, "stacktrace", "frames")
    if not frames:
        threads = get_values(get_path(data, "threads"))
        if threads and len(threads) == 1:
            frames = get_path(threads, 0, "stacktrace", "frames")

    default = None
    for frame in reversed(frames or ()):
        if frame is None:
            continue
        if frame_filter is not None:
            if not frame_filter(frame):
                continue
        if frame.get("in_app"):
            return frame
        if default is None:
            default = frame

    if default:
        return default


def get_crash_location(data):
    # This function lives in a different file in the Sentry codebase (sentry/eventtypes/error.py), but it made its way
    # here because that file didn't make it to the part of Sentry that we vendored.

    frame = get_crash_frame_from_event_data(
        data,
        frame_filter=lambda x: x.get("function") not in (None, "<redacted>", "<unknown>"),
    )
    if frame is not None:
        func = get_function_name_for_frame(frame, data.get("platform"))
        return frame.get("filename") or frame.get("abs_path"), func
    return None, None
