def _make_key_value(val):
    # strip, and then split on '='
    return val.strip().split("=", 1)


def parse_auth_header(header):
    # KvS: isn't this always either bytes or strings? I'd like to learn more (first quickly, and then formalizing for
    # actual uses)
    # https://github.com/getsentry/sentry/pull/12108 is the non-explanation
    if isinstance(header, bytes):
        print("it's bytes, probably always so")
        header = header.decode("latin1")
    else:
        print("not bytes, already a string")

    try:
        # the the RHS of the header (question: what's left of the space), split it on "," and put the x=y pairs into a
        # dict as key-values
        return dict(map(_make_key_value, header.split(" ", 1)[1].split(",")))
    except Exception:
        return {}
