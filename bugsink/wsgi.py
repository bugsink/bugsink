"""
WSGI config for bugsink project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

import django

from django.core.handlers.wsgi import WSGIHandler, WSGIRequest
from django.core.exceptions import DisallowedHost
from django.http.request import split_domain_port, validate_host

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bugsink_conf')


def allowed_hosts_fix_suggestions(domain, allowed_hosts):
    if not allowed_hosts:
        # If ALLOWED_HOSTS is not set at all (which takes quite some work in Bugsink, i.e. is unlikely) fix _that_
        return "You may need to add %r to ALLOWED_HOSTS (currently empty)." % domain

    # Candidate suggestions to add as 'Host' headers on a proxy; we generally don't want to suggest localhost-like
    # values for this, and since there are various places where localhost-like values get added (`deduce_allowed_hosts`
    # and `get_host`) they must be taken back out.
    candidates = [host for host in allowed_hosts if host not in [".localhost", "localhost", "127.0.1", "[::1]"]]

    if len(candidates) == 1:
        single_candidate = candidates[0]
        return "Make sure your proxy forwards the 'Host: %s' header." % single_candidate
    message += " (currently set to %s), " % repr(allowed_hosts)



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
            self._stream = self.environ["wsgi.input"]

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

        # copied from HttpRequest.get_host() in Django 4.2, with modifications.

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
                # we _always_ start with the mismatch in general terms...
                msg = "Header 'Host: %r' does not match any of allowed hosts: %s." % (domain, allowed_hosts)
                # ...and follow up with specific suggestions (of which we are less sure) after that.
                msg += " " + allowed_hosts_fix_suggestions(domain, allowed_hosts)
            else:
                msg = "Invalid HTTP_HOST header: %r." % host
                msg += (
                    " The domain name provided is not valid according to RFC 1034/1035."
                )
            raise DisallowedHost(msg)

            # from None, because our DisallowedHost is so directly caused by super()'s DisallowedHost that cause and
            # effect are the same, i.e. cause must be hidden from the stacktrace for the sake of clarity.
            raise DisallowedHost(message) from None


class CustomWSGIHandler(WSGIHandler):
    request_class = CustomWSGIRequest


def custom_get_wsgi_application():
    # Like get_wsgi_application, but returns a subclass of WSGIHandler that uses a custom request class.
    django.setup(set_prefix=False)
    return CustomWSGIHandler()


application = custom_get_wsgi_application()
