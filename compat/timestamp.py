import datetime

from django.utils.dateparse import parse_datetime


def parse_timestamp(value):
    """
    > Indicates when the event was created in the Sentry SDK. The format is either a string as defined in RFC 3339 or a
    > numeric (integer or float) value representing the number of seconds that have elapsed since the Unix epoch

    > Timezone is assumed to be UTC if missing.

    > Sub-microsecond precision is not preserved with numeric values due to precision limitations with floats (at least
    > in our systems). With that caveat in mind, just send whatever is easiest to produce.

    > All timestamps in the event protocol are formatted this way.
    """

    if isinstance(value, int) or isinstance(value, float):
        return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)

    return parse_datetime(value)


def format_timestamp(value):
    """the reverse of parse_timestamp"""

    assert isinstance(value, datetime.datetime)
    assert value.tzinfo == datetime.timezone.utc

    return value.isoformat()
