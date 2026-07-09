# copied from:
# https://github.com/getsentry/sentry/blob/93e4acc1f41f6a4c4a204d5bf30690cf4cfd1d28/src/sentry/grouping/strategies/message.py#L15

import re
from itertools import islice
from typing import Match

# changed by Bugsink: removed Sentry grouping-framework imports.

_parameterization_regex = re.compile(
    # The `(?x)` tells the regex compiler to ingore comments and unescaped whitespace,
    # so we can use newlines and indentation for better legibility.
    r"""(?x)
    (?P<email>
        [a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*
    ) |
    (?P<url>
        \b(wss?|https?|ftp)://[^\s/$.?#].[^\s]*
    ) |
    (?P<ip>
        (
            ([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|
            ([0-9a-fA-F]{1,4}:){1,7}:|
            ([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|
            ([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|
            ([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|
            ([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|
            ([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|
            [0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|
            :((:[0-9a-fA-F]{1,4}){1,7}|:)|
            fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|
            ::(ffff(:0{1,4}){0,1}:){0,1}
            ((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}
            (25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|
            ([0-9a-fA-F]{1,4}:){1,4}:
            ((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}
            (25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\b
        ) |
        (
            \b((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}
            (25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\b
        )
    ) |
    (?P<uuid>
        \b
            [0-9a-fA-F]{8}-
            [0-9a-fA-F]{4}-
            [0-9a-fA-F]{4}-
            [0-9a-fA-F]{4}-
            [0-9a-fA-F]{12}
        \b
    ) |
    (?P<sha1>
        \b[0-9a-fA-F]{40}\b
    ) |
    (?P<md5>
        \b[0-9a-fA-F]{32}\b
    ) |
    (?P<date>
        (
            (\d{4}-[01]\d-[0-3]\dT[0-2]\d:[0-5]\d:[0-5]\d\.\d+([+-][0-2]\d:[0-5]\d|Z))|
            (\d{4}-[01]\d-[0-3]\dT[0-2]\d:[0-5]\d:[0-5]\d([+-][0-2]\d:[0-5]\d|Z))|
            (\d{4}-[01]\d-[0-3]\dT[0-2]\d:[0-5]\d([+-][0-2]\d:[0-5]\d|Z))
        ) |
        (
            \b(?:(Sun|Mon|Tue|Wed|Thu|Fri|Sat)\s+)?
            (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+
            ([\d]{1,2})\s+
            ([\d]{2}:[\d]{2}:[\d]{2})\s+
            [\d]{4}
        ) |
        (
            \b(?:(Sun|Mon|Tue|Wed|Thu|Fri|Sat),\s+)?
            (0[1-9]|[1-2]?[\d]|3[01])\s+
            (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+
            (19[\d]{2}|[2-9][\d]{3})\s+
            (2[0-3]|[0-1][\d]):([0-5][\d])
            (?::(60|[0-5][\d]))?\s+
            ([-\+][\d]{2}[0-5][\d]|(?:UT|GMT|(?:E|C|M|P)(?:ST|DT)|[A-IK-Z]))
        ) |
        (datetime.datetime\(.*?\))
    ) |
    (?P<hex>
        \b0[xX][0-9a-fA-F]+\b
    ) |
    (?P<float>
        -\d+\.\d+\b |
        \b\d+\.\d+\b
    ) |
    (?P<int>
        -\d+\b |
        \b\d+\b
    ) |
    (?P<quoted_str>
        # The `=` here guarantees we'll only match the value half of key-value pairs,
        # rather than all quoted strings
        ='([^']+)' |
        ="([^"]+)"
    ) |
    (?P<bool>
        # The `=` here guarantees we'll only match the value half of key-value pairs,
        # rather than all instances of the words 'true' and 'false'.
        =True |
        =true |
        =False |
        =false
    )
"""
)


def normalize_message_for_grouping(message: str) -> str:
    """Replace values from a group's message with placeholders (to hide P.I.I. and
    improve grouping when no stacktrace is available) and trim to at most 2 lines.
    """
    trimmed = "\n".join(
        # If there are multiple lines, grab the first two non-empty ones.
        islice(
            (x for x in message.splitlines() if x.strip()),
            2,
        )
    )
    if trimmed != message:
        trimmed += "..."

    def _handle_match(match: Match[str]) -> str:
        # Find the first (should be only) non-None match entry, and sub in the placeholder. For
        # example, given the groupdict item `('hex', '0x40000015')`, this returns '<hex>' as a
        # replacement for the original value in the string.
        for key, value in match.groupdict().items():
            if value is not None:
                # changed by Bugsink: removed Sentry metrics call.
                # For `quoted_str` and `bool` we want to preserve the `=` symbol, which we include in
                # the match in order not to replace random quoted strings and the words 'true' and 'false'
                # in contexts other than key-value pairs
                return f"=<{key}>" if key in ["quoted_str", "bool"] else f"<{key}>"
        return ""

    return _parameterization_regex.sub(_handle_match, trimmed)
