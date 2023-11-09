def parse_auth_header(header):
    # Sentry has code in place here to parse bytes (from latin1). Based on how Django works, I'd like to think that's
    # not needed. https://github.com/getsentry/sentry/pull/12108 is the non-explanation
    # if isinstance(header, bytes): header = header.decode("latin1")

    try:
        _, rhs = header.split(" ", 1)
        return {
            k: v for (k, v) in [part.strip().split('=', 1) for part in rhs.split(",")]
        }
    except Exception:
        return {}
