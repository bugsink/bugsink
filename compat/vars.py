def unrepr(value):
    """The Sentry Client (at least the Python one) makes particular choices when serializing the data as JSON. In
    general, not everything can be serialized, so they call repr(). However, they also call repr when this is not
    strictly necessary, with the note "For example, it's useful to see the difference between a unicode-string and a
    bytestring when viewing a stacktrace." (see `_should_repr_strings`)

    When receiving such data, especially when nested inside e.g. a dict or list, we must take care to not render both
    both the quote for "string data in a json dict" and the quote for "repr has been called on a string", like so:

    {"foo": "'bar'", ...}  <= WRONG

    This would put potentially put human debuggers on the path of trying to figure out where the spurious quotes would
    come from in the application that's being debugged.

    The following code at least tackles that particular problem.

    Notes on compat (as of late 2023):

    * GlitchTip has this wrong; sentry suffered from this in the past: https://github.com/getsentry/sentry/issues/15912
    * Sentry (and we) renders the _keys_ in dicts wrong, because for strings repr() isn't called client side. However,
      "naked" (non-string) symbols cannot occur in Python dicts, so this can never cause confusion as mentioned above.
    """
    if isinstance(value, dict):
        return "{" + (", ".join(f"{k}: {unrepr(v)}" for k, v in value.items())) + "}"
    if isinstance(value, list):
        return "[" + (", ".join(f"{unrepr(v)}" for v in value)) + "]"
    return value
