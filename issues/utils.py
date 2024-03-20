import hashlib
from typing import List, Optional

from sentry.eventtypes.base import DefaultEvent
from sentry.eventtypes.error import ErrorEvent


def default_issue_grouper(title: str, culprit: str, type_) -> str:
    return title + " ⋄ " + culprit + " ⋄ " + type_


def generate_issue_grouper(title: str, culprit: str, type_, extra: Optional[List[str]] = None) -> str:
    if extra:
        return "".join(
            [
                default_issue_grouper(title, culprit, type_)
                if part == "{{ default }}"
                else part
                for part in extra
            ]
        )
    return default_issue_grouper(title, culprit, type_)


def get_issue_grouper_for_data(data):
    if "exception" in data and data["exception"]:
        eventtype = ErrorEvent()
    else:
        eventtype = DefaultEvent()

    metadata = eventtype.get_metadata(data)

    title = eventtype.get_title(metadata)
    culprit = eventtype.get_location(data)
    return generate_issue_grouper(title, culprit, type(eventtype).__name__, data.get("fingerprint"))


def get_hash_for_data(data):
    """Generate hash used for grouping issues (note: not a cryptographically secure hash)"""
    # NOTE: issue_grouper should be renamed to what it _is_ (hash is accidental, 'grouper', or 'key' maybe?
    issue_grouper = get_issue_grouper_for_data(data)
    return hashlib.md5(issue_grouper.encode()).hexdigest()


# utilities related to storing and retrieving release-versions; we use the fact that sentry (and we've adopted their
# limitation) disallows the use of newlines in release-versions, so we can use newlines as a separator

def parse_lines(s):
    # Remove the last element, which is an empty string because of the trailing newline (\n as terminator not separator)
    return s.split("\n")[:-1]


def serialize_lines(l):
    return "".join([e + "\n" for e in l])


def filter_qs_for_fixed_at(qs, release):
    return qs.filter(fixed_at__contains=release + "\n")


def exclude_qs_for_fixed_at(qs, release):
    return qs.exclude(fixed_at__contains=release + "\n")
