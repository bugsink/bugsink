import hashlib
from typing import List, Optional

from sentry.eventtypes.base import DefaultEvent
from sentry.eventtypes.error import ErrorEvent


def default_hash_input(title: str, culprit: str, type_) -> str:
    return title + culprit + type_


def generate_hash(
    title: str, culprit: str, type_, extra: Optional[List[str]] = None
) -> str:
    """Generate insecure hash used for grouping issues"""
    if extra:
        hash_input = "".join(
            [
                default_hash_input(title, culprit, type_)
                if part == "{{ default }}"
                else part
                for part in extra
            ]
        )
    else:
        hash_input = default_hash_input(title, culprit, type_)
    return hashlib.md5(hash_input.encode()).hexdigest()


def get_hash_for_data(data):
    if "exception" in data and data["exception"]:
        eventtype = ErrorEvent()
    else:
        eventtype = DefaultEvent()

    metadata = eventtype.get_metadata(data)

    title = eventtype.get_title(metadata)
    culprit = eventtype.get_location(data)
    return generate_hash(title, culprit, type(eventtype).__name__, data.get("fingerprint"))
