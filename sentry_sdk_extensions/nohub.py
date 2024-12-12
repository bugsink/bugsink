# Like the default sentry_sdk, but without hubs, scopes, transactions and all kinds of other magic. Just a way to send
# an error synchronously when it happens.

import time
import uuid
import sys
import logging
import json
import requests
from contextlib import contextmanager

from sentry_sdk.utils import exc_info_from_error, event_from_exception, walk_exception_chain
from sentry_sdk.serializer import serialize
from sentry_sdk.integrations.django.templates import get_template_frame_from_exception


from compat.dsn import get_envelope_url, get_header_value

# the lazy choice: I've already got loggers set up for bugsink; I'll just use them. Better would be: just use "sentry"
logger = logging.getLogger("bugsink.sentry")


def get_default_client_options():
    return {
        "include_local_variables": True,
        "include_source_context": True,
        "max_value_length": 1000,
    }


def capture_exception(dsn, error=None, client_options=None):
    try:
        if error is not None:
            exc_info = exc_info_from_error(error)
        else:
            exc_info = sys.exc_info()

        event, hint = event_from_exception(exc_info, client_options=client_options)
        event["event_id"] = uuid.uuid4().hex
        event["timestamp"] = time.time()
        event["platform"] = "python"

        # this makes our setup Django-specific; it may not be what we generally want, but it's what I need now.
        process_django_templates(event, hint)

        serialized_event = serialize(event)
    except Exception as e:
        logger.warning("sentry_sdk_extensions.nohub.capture_exception Error: %s", e)
        return None

    return send_to_server(dsn, serialized_event)


def send_to_server(dsn, data):
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Sentry-Auth": get_header_value(dsn),
        }
        data_bytes = json.dumps(data).encode("utf-8")

        # the smallest possible envelope:
        data_bytes = (b'{"event_id": "%s"}\n{"type": "event"}\n' % (data["event_id"]).encode("utf-8") + data_bytes)

        response = requests.post(
            get_envelope_url(dsn),
            headers=headers,
            data=data_bytes,
        )

        response.raise_for_status()
        return data["event_id"]
    except Exception as e:
        logger.warning("sentry_sdk_extensions.nohub.send_to_server Error: %s", e)
        return None


@contextmanager
def capture_exceptions(dsn, client_options=None):
    try:
        yield
    except Exception as e:
        capture_exception(dsn, error=e, client_options=client_options)
        raise


def process_django_templates(event, hint):
    # Copied from sentry_sdk.integrations.django, but in a way that way can reference it (it's an inner function at the
    # original location)
    # Only works when TEMPLATES['OPTIONS']['debug'] is True (for obvious reasons).

    if hint is None:
        return event

    exc_info = hint.get("exc_info", None)

    if exc_info is None:
        return event

    exception = event.get("exception", None)

    if exception is None:
        return event

    values = exception.get("values", None)

    if values is None:
        return event

    for exception, (_, exc_value, _) in zip(
        reversed(values), walk_exception_chain(exc_info)
    ):
        frame = get_template_frame_from_exception(exc_value)
        if frame is not None:
            frames = exception.get("stacktrace", {}).get("frames", [])

            for i in reversed(range(len(frames))):
                f = frames[i]
                if (
                    f.get("function") in ("Parser.parse", "parse", "render")
                    and f.get("module") == "django.template.base"
                ):
                    i += 1
                    break
            else:
                i = len(frames)

            frames.insert(i, frame)

    return event
