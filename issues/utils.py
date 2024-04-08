from sentry.eventtypes.base import DefaultEvent
from sentry.eventtypes.error import ErrorEvent

from django.utils.encoding import force_str


def default_issue_grouper(title: str, transaction: str, event_type_name: str) -> str:
    return title + " ⋄ " + transaction + " ⋄ " + event_type_name


def get_issue_grouper_for_data(data):
    if "exception" in data and data["exception"]:
        eventtype = ErrorEvent()
    else:
        eventtype = DefaultEvent()

    title = eventtype.get_title(data)
    transaction = force_str(data.get("transaction") or "")
    fingerprint = data.get("fingerprint")
    event_type_name = type(eventtype).__name__

    if fingerprint:
        return " ⋄ ".join([
            default_issue_grouper(title, transaction, event_type_name) if part == "{{ default }}" else part
            for part in fingerprint
        ])

    return default_issue_grouper(title, transaction, event_type_name)


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
