import re
from datetime import datetime

from compat.dsn import validate_sentry_dsn


_RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_UUID32 = re.compile(r"^[0-9a-fA-F]{32}$")
_UUID36 = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class ParseError(Exception):
    pass


# ## Item header validators

def _validate_dsn(v):
    try:
        validate_sentry_dsn(v)
    except ValueError as e:
        raise ParseError(f'Envelope header "dsn" invalid: {e}')


def _validate_sdk(v):
    if not isinstance(v, dict):
        raise ParseError('Envelope header "sdk" must be an object')


def _validate_sent_at(v):
    if not isinstance(v, str) or not _RFC3339_Z.match(v):
        raise ParseError(f'Envelope header "sent_at" must be an RFC3339 UTC timestamp ending in Z: {v}')

    try:
        datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        datetime.fromisoformat(v.replace("Z", "+00:00"))


def _validate_event_id(v):
    if not isinstance(v, str) or not (_UUID32.match(v) or _UUID36.match(v)):
        raise ParseError(f'Envelope header "event_id" must be a valid UUID string: {v}')


envelope_validators = {
    "dsn": _validate_dsn,
    "sdk": _validate_sdk,
    "sent_at": _validate_sent_at,
    "event_id": _validate_event_id,
}


def validate_envelope_headers(headers):
    for key, val in headers.items():
        if key in envelope_validators:
            envelope_validators[key](val)


_allowed_types = {
    "event", "transaction", "attachment", "session", "sessions", "feedback", "user_report", "client_report",
    "replay_event", "replay_recording", "profile", "profile_chunk", "check_in", "log", "otel_log"
}


def _validate_type(v):
    if not isinstance(v, str) or v not in _allowed_types:
        raise ParseError(f'Item header "type" must be one of {_allowed_types}, got: {v}')


def _validate_length(v):
    if not isinstance(v, int) or v < 0:
        raise ParseError(f'Item header "length" must be a non-negative integer, got: {v}')


def _validate_filename(v):
    if not isinstance(v, str) or '/' in v or '\\' in v:
        raise ParseError(f'Attachment header "filename" must be a simple filename without path: {v}')


_allowed_attachment_types = {
    "event.attachment", "event.minidump", "event.applecrashreport", "unreal.context", "unreal.logs",
    "event.view_hierarchy"
}


# ## Item header validators

def _validate_attachment_type(v):
    if not isinstance(v, str) or v not in _allowed_attachment_types:
        raise ParseError(f'Attachment header "attachment_type" invalid: {v}')


def _validate_content_type(v):
    if not isinstance(v, str) or '/' not in v:
        raise ParseError(f'Header "content_type" must be a valid MIME type string: {v}')


def _validate_item_count(v):
    if not isinstance(v, int) or v < 0:
        raise ParseError(f'Log header "item_count" must be a non-negative integer, got: {v}')


def _validate_log_content_type(v):
    if v != "application/vnd.sentry.items.log+json":
        raise ParseError(f'Log header "content_type" must be "application/vnd.sentry.items.log+json", got: {v}')


item_validators = {
    "type": _validate_type,
    "length": _validate_length,
    "filename": _validate_filename,
    "attachment_type": _validate_attachment_type,
    "content_type": _validate_content_type,
    "item_count": _validate_item_count,
}


def validate_item_headers(headers):
    for key, val in headers.items():
        if key in item_validators:
            item_validators[key](val)

    if headers.get("type") == "log" and "content_type" in headers:
        _validate_log_content_type(headers["content_type"])

    if headers.get("type") == "replay_recording":
        if "length" not in headers:
            raise ParseError('Replay recording items must include a "length" header')
