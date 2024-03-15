from sentry_sdk.utils import capture_internal_exceptions, current_stacktrace
import sentry_sdk


class AdHocException(Exception):
    pass


def capture_stacktrace(message):
    """
    Capture the current stacktrace and send it to Sentry; the standard sentry_sdk does not provide this; it either
    allows for sending arbitrary messages (but without local variables on your stacktrace) or it allows for sending
    exceptions (but you have to raise an exception to capture the stacktrace).
    """
    client_options = sentry_sdk.client.get_options()
    event = {}
    with capture_internal_exceptions():
        stacktrace = current_stacktrace(client_options["with_locals"])
        stacktrace["frames"].pop()  # Remove the last frame, which is the present function
        event["threads"] = {
            "values": [
                {
                    "stacktrace": stacktrace,
                    "crashed": False,
                    "current": True,
                }
            ]
        }

    event["level"] = "error"
    event["logentry"] = {"message": message}
    sentry_sdk.capture_event(event)


def capture_stacktrace_2(message):
    """
    Capture the current stacktrace and send it to Sentry. Like capture_stacktrace, but using an "Ad Hoc" Exception.
    This allows us to use the standard sentry_sdk.capture_exception function, and our stacktrace to show up as an
    exception on the server-side.

    In good old Python tradition, we've just tacked a "_2" onto the end of the function name.
    """
    try:
        raise AdHocException(message)
    except AdHocException as e:
        sentry_sdk.capture_exception(e)
