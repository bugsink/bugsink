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
        _, rhs = header.split(" ", 1)
        return {
            k: v for (k, v) in [part.strip().split('=', 1) for part in rhs.split(",")]
        }
    except Exception:
        return {}
