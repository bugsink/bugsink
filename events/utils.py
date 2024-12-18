class IncompleteList(list):
    def __init__(self, lst, cnt):
        super().__init__(lst)
        self.incomplete = cnt


class IncompleteDict(dict):
    def __init__(self, dct, cnt):
        super().__init__(dct)
        self.incomplete = cnt


def annotate_with_meta(values, meta_values):
    """
    Use the meta_values (values attr of a "_meta" key) to annotate the values, in particular to add information about
    which lists/dicts have been trimmed.

    This depends on an ondocumented API of the Python Sentry SDK; we've just reverse-engineered the format of the
    "_meta" values.

    From the Sentry SDK source code, one could conclude that there are various pieces of info (I've seen "rem", "len",
    "val", and "err" mentioned as keys and "!limit" as a value) but I've not actually been able to get the Sentry SDK
    to emit records with the "!limit" value, and there are no tests for it, so I'm not sure how it's supposed to work.
    For now, I'm basing myself on what I've actually seen in the wild. (Also: I'm less worried about pruning in depth
    than in breadth, because in the case of in-depth pruning the fallback is still to repr() the remaining stuff, so
    you don't end up with silently trimmed data).

    See also:
    https://github.com/getsentry/relay/blob/b3ecbb980c63be542547cf346f433061f69c4bba/relay-protocol/src/meta.rs#L417

    The values are modified in-place.
    """

    for str_i, meta_value in meta_values.items():
        annotate_exception_with_meta(values[int(str_i)], meta_value)


def annotate_exception_with_meta(exception, meta_value):
    frames = exception.get("stacktrace", {}).get("frames", {})
    meta_frames = meta_value.get("stacktrace", {}).get("frames", {})

    for str_i, meta_frame in meta_frames.items():
        annotate_frame_with_meta(frames[int(str_i)], meta_frame)


def annotate_frame_with_meta(frame, meta_frame):
    frame["vars"] = annotate_var_with_meta(frame["vars"], meta_frame["vars"])


def annotate_var_with_meta(var, meta_var):
    """
    'var' is a (potentially trimmed) list or dict, 'meta_var' is a dict describing the trimming.
    """
    assert isinstance(var, (list, dict))

    if isinstance(var, list):
        Incomplete = IncompleteList
        at = lambda k: int(k)  # noqa; (for some reason the meta_k for list lookups is stored as a string)

    else:  # isinstance(var, dict):
        Incomplete = IncompleteDict
        at = lambda k: k  # noqa

    for meta_k, meta_v in meta_var.items():
        if meta_k == "":
            var = Incomplete(var, meta_v["len"] - len(var))
        else:
            var[at(meta_k)] = annotate_var_with_meta(var[at(meta_k)], meta_v)

    return var
