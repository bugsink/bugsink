import traceback
import types

from sentry_sdk.utils import current_stacktrace
import sentry_sdk


class CapturedStacktrace(Exception):
    pass


def capture_stacktrace_using_logentry(message):
    """
    YOU PROBABLY DON'T WANT THIS

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


def capture_stacktrace_using_exception(message):
    """
    Capture the current stacktrace and send it to Sentry _as an CapturedStacktrace with stacktrace context; the standard
    sentry_sdk does not provide this; it either allows for sending arbitrary messages (but without local variables on
    your stacktrace) or it allows for sending exceptions (but you have to raise an exception to capture the stacktrace).

    Implemented by raise-then-capture, which has good support in all sentry-like servers. This should "probably" be
    somewhat equivalent to capture_stacktrace (though it may in fact have more unnecessary tb info).
    """
    try:
        __traceback_hide__ = True  # noqa this magic variable is understood by the sentry sdk to hide the current frame
        raise CapturedStacktrace(message)
    except CapturedStacktrace as e:
        # The captured exception does not actually have the traceback that we need. We have to construct it ourselves.
        # https://stackoverflow.com/questions/78172031/how-to-obtain-an-exception-with-a-traceback-attribute-that-contai
        tb = e.__traceback__
        fb = tb.tb_frame.f_back
        while fb:
            tb = types.TracebackType(tb_next=tb, tb_frame=fb, tb_lasti=fb.f_lasti, tb_lineno=fb.f_lineno)
            fb = tb.tb_frame.f_back

        e.__traceback__ = tb
        sentry_sdk.capture_exception(e)


def capture_stacktrace(message):
    """
    Capture the current stacktrace and send it to Sentry _as an CapturedStacktrace with stacktrace context; the standard
    sentry_sdk does not provide this; it either allows for sending arbitrary messages (but without local variables on
    your stacktrace) or it allows for sending exceptions (but you have to raise an exception to capture the stacktrace).

    Implemented as a mix of the 2 failed attempts above: I inspected and reused the event as it would be generated by
    capture_stacktrace_using_exception and used the stacktrace from capture_stacktrace_using_logentry.
    """
    # with capture_internal_exceptions():   commented out; I'd rather see the exception than swallow it

    # client_options = sentry_sdk.client.get_options()
    # client_options["include_local_variables"]  for this and other parameters to current_stacktrace to
    # current_stacktrace() I'm just going to accept the default values. The default values are fine _to me_ and I'm not
    # in the business of developing a generic set of sentry_sdk_extensions, but rather to have a few extensions that are
    # useful in the context of developing Bugsink, and having another Bugsink to send those to.
    # (The reason not to parse client_options is: Sentry might change their names and I don't want the maintenance)
    stacktrace = current_stacktrace()
    stacktrace["frames"].pop()  # Remove the last frame, which is the present function

    event = {
        'level': 'error',
        'exception': {
            'values': [{
                'mechanism': {
                    'type': 'generic',
                    'handled': True
                },
                'module': stacktrace["frames"][-1]["module"],
                'type': 'CapturedStacktrace',
                'value': message,
                'stacktrace': stacktrace,
            }]
        }
    }
    sentry_sdk.capture_event(event)


def capture_or_log_exception(e, logger):
    try:
        if sentry_sdk.is_initialized():
            sentry_sdk.capture_exception(e)
        else:
            # this gnarly approach makes it so that each line of the traceback gets the same prefixes (dates etc)
            for bunch_of_lines in traceback.format_exception(e):
                for line in bunch_of_lines.splitlines():
                    # Note: when .is_initialized() is True, .error is spammy (it gets captured) but we don't have that
                    # problem in this branch.
                    logger.error(line)
    except Exception as e2:
        # We just never want our error-handling code to be the cause of an error.
        print("Error in capture_or_log_exception", str(e2), "during handling of", str(e))
