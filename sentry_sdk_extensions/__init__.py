from sentry_sdk.utils import capture_internal_exceptions, current_stacktrace
import sentry_sdk


class AdHocException(Exception):
    pass


def capture_stacktrace(message):
    """
    Capture the current stacktrace and send it to Sentry _as a log entry with stacktrace context; the standard
    sentry_sdk does not provide this; it either allows for sending arbitrary messages (but without local variables on
    your stacktrace) or it allows for sending exceptions (but you have to raise an exception to capture the stacktrace).

    Support for this (logging with stacktrace) server-side (as of March 15 2024):

    * Bugsink: no stacktrace info displayed
    * GlitchTip: no stacktrace info displayed
    * Sentry: not checked
    """
    event = {}

    # with capture_internal_exceptions():   commented out; I'd rather see the exception than swallow it

    # client_options = sentry_sdk.client.get_options()
    # client_options["include_local_variables"]  for this and other parameters to current_stacktrace to
    # current_stacktrace() I'm just going to accept the default values. The default values are fine _to me_ and I'm not
    # in the business of developing a generic set of sentry_sdk_extensions, but rather to have a few extensions that are
    # useful in the context of developing Bugsink, and having another Bugsink to send those to.
    # (The reason not to parse client_options is: Sentry might change their names and I don't want the maintenance)

    stacktrace = current_stacktrace()
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
