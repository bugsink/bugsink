import os

import django

from django.core.handlers.wsgi import WSGIHandler, WSGIRequest
from django.core.exceptions import DisallowedHost
from django.http.request import split_domain_port, validate_host
from django.core.validators import validate_ipv46_address
from django.core.exceptions import ValidationError

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bugsink_conf')


def is_ip_address(value):
    try:
        validate_ipv46_address(value)
        return True
    except ValidationError:
        return False


def allowed_hosts_error_message(domain, allowed_hosts):
    # Start with the plain statement of fact: x not in y.
    msg = "'Host: %s' as sent by browser/proxy not in ALLOWED_HOSTS=%s. " % (domain, allowed_hosts)

    suggestable_allowed_hosts = [host for host in allowed_hosts if host not in ["localhost", ".localhost", "127.0.0.1"]]
    if len(suggestable_allowed_hosts) == 0:
        proxy_suggestion = "your.host.example"
    else:
        proxy_suggestion = " | ".join(suggestable_allowed_hosts)

    if domain == "localhost" or is_ip_address(domain):
        # in these cases Proxy misconfig is the more likely culprit. Point to that _first_ and (while still mentioning
        # ALLOWED_HOSTS); don't mention the specific domain that was used as a likely "good value" for ALLLOWED_HOSTS.
        return msg + "Configure proxy to use 'Host: %s' or add the desired host to ALLOWED_HOSTS." % proxy_suggestion

    # the domain looks "pretty good"; be verbose/explicit about the 2 possible changes in config.
    return msg + "Add '%s' to ALLOWED_HOSTS or configure proxy to use 'Host: %s'." % (domain, proxy_suggestion)


class NoopClose:
    """Delegator: Gunicorn's Body doesn't implement .close(); Django calls that it in request.body's finally clause.
    That .close() call in itself is slightly surprising to me (and I have not copied it in my own streaming reads) b/c
    the [WSGI spec](https://peps.python.org/pep-3333/#input-and-error-streams) says:

    > Applications conforming to this specification must not use any other methods or attributes of the input or errors
    > objects. In particular, applications must not attempt to close these streams, even if they possess close()
    > methods.

    In the end, Django conforms to spec because LimitedStream _also_ drops the .close() (it's subclassing `io.IOBase`),
    but one wonders why they call it in the first place. Anyway, just stub it and we're good.
    """

    def __init__(self, stream):
        self._stream = stream

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def close(self):
        return None


class CustomWSGIRequest(WSGIRequest):
    """
    Custom WSQIRequest subclass with 3 fixes/changes:

    * Chunked Transfer Encoding (Django's behavior is broken)
    * Skip ALLOWED_HOSTS validation for /health/ endpoints (see #140)
    * Better error message for disallowed hosts

    Note: used in all servers (in gunicorn through wsgi.py; in Django's runserver through WSGI_APPLICATION)
    """

    def __init__(self, environ):
        """
        We override this method to fix Django's behavior in the context of Chunked Transfer Encoding (Django's
        behavior, behind Gunicorn, is broken). Django's breakage is in the super() of this method, in the combination
        [1] defaulting (through a set-on-catch) to 0 for CONTENT_LENGTH when not present and [2] settings self._stream
        to a LimitedStream with that length. The lines below undo this behavior iff the HTTP_TRANSFER_ENCODING header
        is present. See:
        * https://code.djangoproject.com/ticket/35838   (The Django problem)
        * https://github.com/bugsink/bugsink/issues/9   (Why we need a fix)
        """
        super().__init__(environ)

        if "CONTENT_LENGTH" not in environ and "HTTP_TRANSFER_ENCODING" in environ:
            self._stream = NoopClose(self.environ["wsgi.input"])

    def get_host(self):
        """
        We override this method to provide a more informative error message when the host is disallowed, i.e. we include
        the current value of ALLOWED_HOSTS in the error message. That this is useful for debugging is self-evident.
        We're leaking a bit of information here, but I don't think it's too much TBH -- especially in the light of ssl
        certificates being specifically tied to the domain name.
        """
        if self.path.startswith == "/health/":
            # For /health/ endpoints, we skip the ALLOWED_HOSTS validation (see #140).
            return self._get_raw_host()

        # copied from HttpRequest.get_host() in Django 5.2, with modifications.

        host = self._get_raw_host()

        # Allow variants of localhost if ALLOWED_HOSTS is empty and DEBUG=True.
        from django.conf import settings
        allowed_hosts = settings.ALLOWED_HOSTS
        if settings.DEBUG and not allowed_hosts:
            allowed_hosts = [".localhost", "127.0.0.1", "[::1]"]

        domain, port = split_domain_port(host)
        if domain and validate_host(domain, allowed_hosts):
            return host
        else:
            if domain:
                msg = allowed_hosts_error_message(domain, allowed_hosts)

            else:
                msg = "Invalid HTTP_HOST header: %r." % host
                msg += (
                    " The domain name provided is not valid according to RFC 1034/1035."
                )
            raise DisallowedHost(msg)


class CustomWSGIHandler(WSGIHandler):
    request_class = CustomWSGIRequest


def custom_get_wsgi_application():
    # Like get_wsgi_application, but returns a subclass of WSGIHandler that uses a custom request class.
    django.setup(set_prefix=False)
    return CustomWSGIHandler()


application = custom_get_wsgi_application()
