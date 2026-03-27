import datetime

from django.utils.dateparse import parse_datetime
from bugsink.utils import assert_


def parse_timestamp(value):
    """
    > Indicates when the event was created in the Sentry SDK. The format is either a string as defined in RFC 3339 or a
    > numeric (integer or float) value representing the number of seconds that have elapsed since the Unix epoch

    > Timezone is assumed to be UTC if missing.

    > Sub-microsecond precision is not preserved with numeric values due to precision limitations with floats (at least
    > in our systems). With that caveat in mind, just send whatever is easiest to produce.

    > All timestamps in the event protocol are formatted this way.

    This function returns None for invalid input.
    """
    # NOTE: the fact that we return None for invalid input strikes me as surprising when revisiting this code; but ATM
    # I don't have the time to go through all the callsites to see if they may have become to depend on this behavior.

    if isinstance(value, int) or isinstance(value, float):
        return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)

    result = parse_datetime(value)
    if result is not None and result.tzinfo is None:
        return result.replace(tzinfo=datetime.timezone.utc)

    return result


def format_timestamp(value):
    """the reverse of parse_timestamp"""

    assert_(isinstance(value, datetime.datetime))
    assert_(value.tzinfo == datetime.timezone.utc)

    return value.isoformat()
