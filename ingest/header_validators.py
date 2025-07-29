import re
from datetime import datetime

from compat.dsn import validate_sentry_dsn
from .exceptions import ParseError


# Based on the documentation here:
#
#   https://develop.sentry.dev/sdk/data-model/envelopes/
#   https://develop.sentry.dev/sdk/data-model/envelope-items/
#
# From the docs, we deduced validation for
#
# * envelope headers -> all of them
# * item headers -> only those that are relevant for "event" items


_RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_UUID32 = re.compile(r"^[0-9a-fA-F]{32}$")
_UUID36 = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def validate_dsn(v):
    try:
        validate_sentry_dsn(v)
    except ValueError as e:
        raise ParseError(f'Envelope header "dsn" invalid: {e}')


def validate_sdk(v):
    if not isinstance(v, dict):
        raise ParseError('Envelope header "sdk" must be an object')


def validate_sent_at(v):
    if not isinstance(v, str) or not _RFC3339_Z.match(v):
        raise ParseError(f'Envelope header "sent_at" must be an RFC3339 UTC timestamp ending in Z: {v}')

    try:
        datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        datetime.fromisoformat(v.replace("Z", "+00:00"))


def validate_event_id(v):
    if not isinstance(v, str) or not (_UUID32.match(v) or _UUID36.match(v)):
        raise ParseError(f'Envelope header "event_id" must be a valid UUID string: {v}')


envelope_validators = {
    "dsn": validate_dsn,
    "sdk": validate_sdk,
    "sent_at": validate_sent_at,
    "event_id": validate_event_id,
}


def validate_envelope_headers(headers):
    for key, val in headers.items():
        if key in envelope_validators:
            envelope_validators[key](val)


ALLOWED_TYPES = {
    "event", "transaction", "attachment", "session", "sessions", "feedback", "user_report", "client_report",
    "replay_event", "replay_recording", "profile", "profile_chunk", "check_in", "log", "otel_log"
}


def validate_type(v):
    return
    # alternatively (1):
    # if v not in _allowed_types:
    # Sentry's protocol might add new item types in the future; we don't want to raise an error for those.
    # logger.warning(f'Item header "type" is not recognized: {v}.'
    #
    # alternatively (2):
    # raise ParseError(f'Item header "type" must be one of {_allowed_types}, got: {v}')


def _validate_length(v):
    if not isinstance(v, int) or v < 0:
        raise ParseError(f'Item header "length" must be a non-negative integer, got: {v}')


item_validators = {
    "type": validate_type,
    "length": _validate_length,
}


def validate_item_headers(headers):
    if headers.get("type") != "event":
        # Only validate item headers for events. Reason: it's the only type of event that we actually process; rather
        # than trying to keep the validation in sync with for a part of the protocol that we don't use, we skip it.
        return

    for key, val in headers.items():
        if key in item_validators:
            item_validators[key](val)
