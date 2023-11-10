import urllib.parse


def _get_url(sentry_dsn, ingest_method):
    parts = urllib.parse.urlsplit(sentry_dsn)

    # note: we don't replicate Sentry's requirement that a project id must be an int
    path_before_api, project_id = parts.path.rsplit("/", 1)

    return (
        parts.scheme + "://" + parts.hostname + (":" + str(parts.port) if parts.port else "") +
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

        # this refers to the Sentry Protocol Version. It's hard to find documentation about this, but the current (late
        # 2023) value is 7, and this has been the sentry-python's version since its Initial commit in June 2018.
        "sentry_version": "7",

        # sentry_secret is deprecated, as mentioned elsewhere in the code.
        # sentry_client ... may be useful, let's figure that out later TODO
    }.items())
