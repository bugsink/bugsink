# Like the default sentry_sdk, but without hubs, scopes, transactions and all kinds of other magic. Just a way to send
# an error synchronously when it happens.

import time
import uuid
import sys
import logging
import json
import requests
from contextlib import contextmanager

from sentry_sdk.utils import exc_info_from_error, event_from_exception
from sentry_sdk.serializer import serialize


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
    if error is not None:
        exc_info = exc_info_from_error(error)
    else:
        exc_info = sys.exc_info()

    event, hint = event_from_exception(exc_info, client_options=client_options)
    event["event_id"] = uuid.uuid4().hex
    event["timestamp"] = time.time()
    event["platform"] = "python"

    serialized_event = serialize(event)
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
        return True
    except Exception as e:
        logger.warning("sentry_sdk_extensions.nohub.capture Error: %s", e)
        return False


@contextmanager
def capture_exceptions(dsn, client_options=None):
    try:
        yield
    except Exception as e:
        capture_exception(dsn, error=e, client_options=client_options)
        raise
