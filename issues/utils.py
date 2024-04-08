from sentry.eventtypes.base import DefaultEvent
from sentry.eventtypes.error import ErrorEvent

from django.utils.encoding import force_str


def default_issue_grouper(title: str, transaction: str) -> str:
    return title + " ⋄ " + transaction


def get_issue_grouper_for_data(data):
    if "exception" in data and data["exception"]:
        eventtype = ErrorEvent()
    else:
        eventtype = DefaultEvent()

    type_, value = eventtype.get_exception_type_and_value(data)
    title = get_title_for_exception_type_and_value(type_, value)
    transaction = force_str(data.get("transaction") or "")
    fingerprint = data.get("fingerprint")

    if fingerprint:
        return " ⋄ ".join([
            default_issue_grouper(title, transaction) if part == "{{ default }}" else part
            for part in fingerprint
        ])

    return default_issue_grouper(title, transaction)


def get_title_for_exception_type_and_value(type_, value):
    if not value:
        return type_

    if not isinstance(value, str):
        value = str(value)

    return "{}: {}".format(type_, value.splitlines()[0])


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
