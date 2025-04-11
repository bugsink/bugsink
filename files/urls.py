from django.urls import path
from django.urls import register_converter

from .views import download_file


def regex_converter(passed_regex):
    # copy/pasta w/ issues/urls.py

    class RegexConverter:
        regex = passed_regex

        def to_python(self, value):
            return value

        def to_url(self, value):
            return value

    return RegexConverter


register_converter(regex_converter("[0-9a-f]{40}"), "sha1")


urlpatterns = [
    path('downloads/<sha1:checksum>/', download_file, name='download_file'),
]
