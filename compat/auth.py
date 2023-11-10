def parse_auth_header_value(header_value):
    # Sentry has code in place here to parse bytes (from latin1). Based on how Django works, I'd like to think that's
    # not needed. https://github.com/getsentry/sentry/pull/12108 is the non-explanation
    # if isinstance(header, bytes): header = header.decode("latin1")

    if not header_value.startswith("Sentry "):
        return {}

    key_value_pairs = header_value[len("Sentry "):]

    try:
        return {
            k: v for (k, v) in [kv.strip().split('=', 1) for kv in key_value_pairs.split(",")]
        }
    except Exception:
        return {}
