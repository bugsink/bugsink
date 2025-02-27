from urllib.parse import urlparse

from django.core.mail import EmailMultiAlternatives
from django.template.loader import get_template

from .version import version


def send_rendered_email(subject, base_template_name, recipient_list, context=None):
    if context is None:
        context = {}

    html_content = get_template(base_template_name + ".html").render(context)
    text_content = get_template(base_template_name + ".txt").render(context)

    # Configure and send an EmailMultiAlternatives
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,  # this is settings.DEFAULT_FROM_EMAIL
        to=recipient_list,
    )

    msg.attach_alternative(html_content, "text/html")

    msg.send()


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
    return [url.hostname]


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
        "traces_sample_rate": 0,
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
