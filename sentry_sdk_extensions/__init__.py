import traceback

from sentry_sdk.utils import current_stacktrace
import sentry_sdk


def capture_stacktrace(message):
    """Capture the current stacktrace as an error-level log message."""
    stacktrace = current_stacktrace()
    stacktrace["frames"].pop()  # Remove the last frame, which is the present function

    event = {
        "level": "error",
        "logentry": {"message": message},
        "threads": {
            "values": [{
                "stacktrace": stacktrace,
                "crashed": False,
                "current": True,
            }]
        },
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
