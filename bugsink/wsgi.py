"""
WSGI config for bugsink project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

import django
from django.core.handlers.wsgi import WSGIHandler, WSGIRequest

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bugsink_conf')


class MyWSGIRequest(WSGIRequest):

    def __init__(self, environ):
        super().__init__(environ)

        if "CONTENT_LENGTH" not in environ and "HTTP_TRANSFER_ENCODING" in environ:
            # "unlimit" content length
            self._stream = self.environ["wsgi.input"]


class MyWSGIHandler(WSGIHandler):
    request_class = MyWSGIRequest


def my_get_wsgi_application():
    # Like get_wsgi_application, but returns a subclass of WSGIHandler that uses a custom request class.
    django.setup(set_prefix=False)
    return MyWSGIHandler()


application = my_get_wsgi_application()
