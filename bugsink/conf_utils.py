from urllib.parse import urlparse


from .version import version


def deduce_allowed_hosts(base_url):
    url = urlparse(base_url)
    if url.hostname == "localhost" or url.hostname == "127.0.0.1":
        # Allow all hosts when running locally. All hosts, because in local setups there are a few common scenarios of
        # named-hosts-that-should-still-be-ok, like:
        # * docker containers with a name
        # * /etc/hosts defining an explicit name for localhost
        # * accessing Bugsink on your local network by ip (192.etc)
        # In production setups, the expectation is that deduce_allowed_hosts is not used with localhost/127.0.0.1
        return ["*"]

    # in production setups, we want to be explicit about the allowed hosts; however, we _still_ add localhost and
    # 127.0.0.1 explicitly, to allow for local loopback testing (e.g. health-checks from the same machine). I believe
    # this is OK (i.e. not a security risk) because the goal of ALLOWED_HOSTS is to "prevent an attacker from poisoning
    # caches and triggering password reset emails with links to malicious hosts by submitting requests with a fake HTTP
    # Host header." Without claiming have a full overview of possible attacks, I believe that they all hinge on the fact
    # that the "poisonous host" is a host under the control of the attacker. I fail to see how "localhost" is a
    # meaningful target in such an attack (since the attacker would already have control over the machine).
    #
    # sources:
    # https://stackoverflow.com/questions/30579248/
    # https://docs.djangoproject.com/en/5.2/ref/settings/#allowed-hosts
    # https://code.djangoproject.com/ticket/28693 (the main source for the relation between CSRF and ALLOWED_HOSTS)
    #
    # security-officers disagreeing with this above: feel free to reach out (and set ALLOWED_HOSTS explicitly).
    return [url.hostname] + ["localhost", "127.0.0.1"]


def deduce_script_name(base_url):
    """Extract the path prefix from BASE_URL for subpath hosting support."""

    # On the matter of leading an trailing slashes:
    # https://datatracker.ietf.org/doc/html/rfc3875#section-4.1.13  (the CGI spec) -> SCRIPT_NAME must start with a /
    # trailing slash: doesn't matter https://github.com/django/django/commit/a15a3e9148e9 (but normalized away)
    # So: leading-but-no-trailing slash is what we want.
    # Our usage in STATIC_URL is made consistent with that.
    # Because BASE_URL is documented to be "no trailing slash", the below produces exactly what we want.

    try:
        parsed_url = urlparse(base_url)
        path = parsed_url.path
    except Exception:
        # maximize robustness here: one broken setting shouldn't break the deduction for others (the brokenness of
        # BASE_URL will be manifested elsewhere more explicitly anyway)
        return None

    return path if path not in (None, "", "/") else None


def int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def eat_your_own_dogfood(sentry_dsn, **kwargs):
    """
    Configures your Bugsink installation to send messages to some Bugsink-compatible installation.
    See https://www.bugsink.com/docs/dogfooding/
    """
    import sentry_sdk.serializer
    sentry_sdk.serializer.MAX_DATABAG_DEPTH = float("inf")
    sentry_sdk.serializer.MAX_DATABAG_BREADTH = float("inf")

    if sentry_dsn is None:
        return

    default_kwargs = {
        "dsn": sentry_dsn,

        # Don't event types which are not supported by Bugsink:
        "traces_sample_rate": 0,
        "send_client_reports": False,
        "auto_session_tracking": False,

        "send_default_pii": True,

        # see (e.g.) https://github.com/getsentry/sentry-python/issues/377 for why this is necessary; I really really
        # dislike Sentry's silent dropping of local variables; let's see whether "just send everything" makes for
        # messages that are too big. If so, we might monkey-patch sentry_sdk/serializer.py 's 2 variables named
        # MAX_DATABAG_DEPTH and MAX_DATABAG_BREADTH (esp. the latter)
        # still not a complete solution until https://github.com/getsentry/sentry-python/issues/3209 is fixed
        "max_request_body_size": "always",

        # In actual development, the list below is not needed, because in that case Sentry's SDK is able to distinguish
        # based on the os.cwd() v.s. site-packages. For cases where the Production installation instructions are
        # followed, that doesn't fly though, because we "just install everything" (using pip install), and we need to be
        # explicit. The notation below (no trailing dot or slash) is the correct one (despite not being documented) as
        # evidenced by the line `if item == name or name.startswith(item + "."):` in the sentry_sdk source:
        "in_app_include": [
            "alerts",
            "bsmain",
            "bugsink",
            "compat",
            "events",
            "ee",
            "ingest",
            "issues",
            "files",
            "performance",
            "phonehome",
            "projects",
            "releases",
            "sentry",
            "sentry_sdk_extensions",
            "snappea",
            "tags",
            "teams",
            "theme",
            "users",
        ],
        "release": version,
        "before_send": fingerprint_before_send,
    }

    default_kwargs.update(kwargs)

    sentry_sdk.init(
        **default_kwargs,
    )


# Note: the excessive string-matching in the below is intentional:
# I'd rather have our error-handling code as simple as possible
# instead of relying on all kinds of imports of Exception classes.
def _name(type_):
    try:
        return type_.__module__ + "." + type_.__name__
    except Exception:
        try:
            return type_.__name__
        except Exception:
            return "unknown"


def fingerprint_exc(event, exc_info):
    type_name = _name(exc_info[0])
    # exc = exc_info[1]

    if event["exception"]["values"][-1]["stacktrace"]["frames"][-1]["module"] == "bugsink.wsgi":
        # When and Exception occurs in the WSGI handler, we want to override the fingerprint to exclude the transaction
        # (which is URL-based in the default) because something that occurs at the server-level (e.g. DisallowedHost)
        # would occur for all URLs.
        #
        # Road not taken: overriding event["transaction"] to "wsgi" and event["transaction_info"]["source"] to "custom"
        # would preserve a bit more of the server-side grouping behavior; road-not-taken b/c the (or our?) interface so
        # clearly implies "set fingerprints".
        #
        # Note: arguably, the above might be extended to "anything middleware-related" for the same reasons; we'll do
        # that when we have an actual use-case.
        event['fingerprint'] = ['wsgi', type_name]

    return event


def fingerprint_log_record(event, log_record):
    # (hook for future use)
    return event


def fingerprint_before_send(event, hint):
    if 'exc_info' in hint:
        return fingerprint_exc(event, hint['exc_info'])

    if 'log_record' in hint:
        return fingerprint_log_record(event, hint['log_record'])

    return event
