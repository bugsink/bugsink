import urllib.parse


def _colon_port(port):
    return ":" + str(port) if port else ""


def build_dsn(base_url, project_id, public_key):
    parts = urllib.parse.urlsplit(base_url)

    assert parts.scheme in ("http", "https"), "The BASE_URL setting must be a valid URL (starting with http or https)."
    assert parts.hostname, "The BASE_URL setting must be a valid URL. The hostname must be set."

    return (f"{ parts.scheme }://{ public_key }@{ parts.hostname }{ _colon_port(parts.port) }" +
            f"{ parts.path }/{ project_id }")


def _get_url(sentry_dsn, ingest_method):
    # https://github.com/getsentry/develop/blob/b24a602de05b/src/docs/sdk/overview.mdx#L94

    parts = urllib.parse.urlsplit(sentry_dsn)

    # note: we don't replicate Sentry's requirement that a project id must be an int
    path_before_api, project_id = parts.path.rsplit("/", 1)

    return (
        parts.scheme + "://" + parts.hostname + _colon_port(parts.port) +
        path_before_api + "/api/" + project_id + "/" + ingest_method + "/")


def get_store_url(sentry_dsn):
    # In sentry's-lingo 'store' just means 'ingest events one by one'
    return _get_url(sentry_dsn, "store")


def get_envelope_url(sentry_dsn):
    return _get_url(sentry_dsn, "envelope")


def get_header_value(sentry_dsn):
    parts = urllib.parse.urlsplit(sentry_dsn)

    return "Sentry " + ", ".join("%s=%s" % (key, value) for key, value in {
        "sentry_key": parts.username,

        # This refers to the Sentry Protocol Version. The current (late 2023) version is 7, and this has been the
        # sentry-python's version since its Initial commit in June 2018.
        # https://github.com/getsentry/develop/blob/b24a602de05b/src/docs/sdk/overview.mdx#L185
        "sentry_version": "7",

        # sentry_secret is deprecated, as mentioned elsewhere in the code.

        # https://github.com/getsentry/develop/blob/b24a602de05b/src/docs/sdk/overview.mdx#L188
        "sentry_client": "bugsink/0.0.1",
    }.items())


def get_sentry_key(sentry_dsn):
    parts = urllib.parse.urlsplit(sentry_dsn)
    return parts.username


def validate_sentry_dsn(sentry_dsn):
    parts = urllib.parse.urlsplit(sentry_dsn)

    if not parts.scheme or not parts.hostname or not parts.username:
        raise ValueError("Invalid Sentry DSN format. It must contain a scheme, hostname, and public_key.")

    if parts.scheme not in ("http", "https"):
        raise ValueError("Invalid Sentry DSN scheme. It must be 'http' or 'https'.")

    if (not parts.path) or ("/" not in parts.path) or (not parts.path.rsplit("/", 1)[1]):
        raise ValueError("Invalid DSN: path must include '/<project_id>'")

    return True
