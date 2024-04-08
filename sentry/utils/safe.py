import collections
import json

from django.utils.encoding import force_str
from django.template.defaultfilters import truncatechars


SENTRY_MAX_VARIABLE_SIZE = 512


def get_path(data, *path, **kwargs):
    """
    Safely resolves data from a recursive data structure. A value is only
    returned if the full path exists, otherwise ``None`` is returned.
    If the ``default`` argument is specified, it is returned instead of ``None``.
    If the ``filter`` argument is specified and the value is a list, it is
    filtered with the given callback. Alternatively, pass ``True`` as filter to
    only filter ``None`` values.
    """
    default = kwargs.pop("default", None)
    f = kwargs.pop("filter", None)
    for k in kwargs:
        raise TypeError("set_path() got an undefined keyword argument '%s'" % k)

    for p in path:
        if isinstance(data, collections.abc.Mapping) and p in data:
            data = data[p]
        elif isinstance(data, (list, tuple)) and -len(data) <= p < len(data):
            data = data[p]
        else:
            return default

    if f and data and isinstance(data, (list, tuple)):
        data = list(filter((lambda x: x is not None) if f is True else f, data))

    return data if data is not None else default


def trim(
    value,
    max_size=SENTRY_MAX_VARIABLE_SIZE,
    max_depth=6,
    object_hook=None,
    _depth=0,
    _size=0,
    **kwargs
):
    """
    Truncates a value to ```MAX_VARIABLE_SIZE```.
    The method of truncation depends on the type of value.
    """
    options = {
        "max_depth": max_depth,
        "max_size": max_size,
        "object_hook": object_hook,
        "_depth": _depth + 1,
    }

    if _depth > max_depth:
        if not isinstance(value, str):
            value = json.dumps(value)
        return trim(value, _size=_size, max_size=max_size)

    elif isinstance(value, dict):
        result = {}
        _size += 2
        for k in sorted(value.keys()):
            v = value[k]
            trim_v = trim(v, _size=_size, **options)
            result[k] = trim_v
            _size += len(force_str(trim_v)) + 1
            if _size >= max_size:
                break

    elif isinstance(value, (list, tuple)):
        result = []
        _size += 2
        for v in value:
            trim_v = trim(v, _size=_size, **options)
            result.append(trim_v)
            _size += len(force_str(trim_v))
            if _size >= max_size:
                break
        if isinstance(value, tuple):
            result = tuple(result)

    elif isinstance(value, str):
        result = truncatechars(value, max_size - _size)

    else:
        result = value

    if object_hook is None:
        return result
    return object_hook(result)
