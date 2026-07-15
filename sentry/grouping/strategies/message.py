# copied from:
# https://github.com/getsentry/sentry/blob/597d25951d00a7d412f3aa047aa9d00fb6c66cd2/src/sentry/grouping/strategies/message.py
#
# changed by Bugsink: removed Sentry grouping-framework imports/strategy wrapper, metrics,
# analytics, event/project rollout logic, and the tiktoken-backed UniqueIdExperiment.

from itertools import islice

from sentry.grouping.parameterization import Parameterizer


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

    parameterizer = Parameterizer(
        regex_pattern_keys=(
            "email",
            "url",
            "hostname",
            "ip",
            "uuid",
            "sha1",
            "md5",
            "date",
            "duration",
            "hex",
            "float",
            "int",
            "quoted_str",
            "bool",
        ),
    )
    return parameterizer.parameterize_all(trimmed)
