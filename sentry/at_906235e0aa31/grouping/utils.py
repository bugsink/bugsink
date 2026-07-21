# copied from:
# https://github.com/getsentry/sentry/blob/906235e0aa31248c7cdec52f300f5801de61fec2/src/sentry/grouping/utils.py
#
# changed by Bugsink: only hash_from_values is vendored here because component.py only needs that helper. Sentry's
# fingerprint-template helpers and stacktrace helper imports are intentionally omitted from this pinned subset.

from hashlib import md5

from django.utils.encoding import force_bytes


def hash_from_values(values):
    result = md5()
    for value in values:
        result.update(force_bytes(value, errors="replace"))
    return result.hexdigest()
