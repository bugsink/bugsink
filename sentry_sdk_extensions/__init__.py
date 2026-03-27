import traceback

from sentry_sdk.utils import current_stacktrace
import sentry_sdk


def capture_stacktrace(message):
    """
    Capture the current stacktrace and send it to Sentry _as an CapturedStacktrace with stacktrace context; the standard
    sentry_sdk does not provide this; it either allows for sending arbitrary messages (but without local variables on
    your stacktrace) or it allows for sending exceptions (but you have to raise an exception to capture the stacktrace).
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
            # this gnarly approach makes it so that the logger prefixes (e.g. snappea task number, dates etc) are shown
            # for each of the lines of the traceback (though it has the disadvantage of time not standing still while
            # we iterate in the loop).
            for bunch_of_lines in traceback.format_exception(e):
                for line in bunch_of_lines.splitlines():
                    # Note: when .is_initialized() is True, .error is spammy (it gets captured) but we don't have that
                    # problem in this branch.
                    logger.error(line)
    except Exception as e2:
        # We just never want our error-handling code to be the cause of an error.
        print("Error in capture_or_log_exception", str(e2), "during handling of", str(e))
