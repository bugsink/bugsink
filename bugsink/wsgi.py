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

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bugsink_conf')


class MyWSGIRequest(WSGIRequest):

    def __init__(self, environ):
        super().__init__(environ)

        if "CONTENT_LENGTH" not in environ and "HTTP_TRANSFER_ENCODING" in environ:
            # "unlimit" content length
            self._stream = self.environ["wsgi.input"]

    def get_host(self):
        """
        We override this method to provide a more informative error message when the host is disallowed, i.e. we include
        the current value of ALLOWED_HOSTS in the error message. That this is useful for debugging is self-evident.
        We're leaking a bit of information here, but I don't think it's too much TBH.
        """

        # Import pushed down to make it absolutely clear we avoid circular importing/loading the wrong thing:
        from django.conf import settings

        try:
            return super().get_host()
        except DisallowedHost as e:
            message = str(e)

            if "ALLOWED_HOSTS" in message:
                # The following 3 lines are copied from HttpRequest.get_host() in Django 4.2
                allowed_hosts = settings.ALLOWED_HOSTS
                if settings.DEBUG and not allowed_hosts:
                    allowed_hosts = [".localhost", "127.0.0.1", "[::1]"]

                message = message[:-1 * len(".")]
                message += ", which is currently set to %s." % repr(allowed_hosts)

            # from None, because our DisallowedHost is so directly caused by super()'s DisallowedHost that cause and
            # effect are the same, i.e. cause must be hidden from the stacktrace for the sake of clarity.
            raise DisallowedHost(message) from None


class MyWSGIHandler(WSGIHandler):
    request_class = MyWSGIRequest


def my_get_wsgi_application():
    # Like get_wsgi_application, but returns a subclass of WSGIHandler that uses a custom request class.
    django.setup(set_prefix=False)
    return MyWSGIHandler()


application = my_get_wsgi_application()
