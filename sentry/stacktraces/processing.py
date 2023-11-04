from sentry.utils.safe import get_path


def get_crash_frame_from_event_data(data, frame_filter=None):
    frames = get_path(
        data, "exception", "values", -1, "stacktrace", "frames"
    ) or get_path(data, "stacktrace", "frames")
    if not frames:
        threads = get_path(data, "threads", "values")
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
