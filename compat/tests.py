from unittest import TestCase

from .dsn import get_store_url, get_envelope_url, get_header_value
from .auth import parse_auth_header_value


class DsnTestCase(TestCase):
    def test_get_store_url(self):
        self.assertEquals(
            "https://hosted.bugsink/api/1/store/",
            get_store_url("https://public_key@hosted.bugsink/1"))

        self.assertEquals(
            "https://hosted.bugsink/some/path/api/1/store/",
            get_store_url("https://public_key@hosted.bugsink/some/path/1"))

    def test_get_store_url_non_default_port(self):
        self.assertEquals(
            "http://hosted.bugsink:8000/api/1/store/",
            get_store_url("http://public_key@hosted.bugsink:8000/1"))

    def test_get_envelope_url(self):
        self.assertEquals(
            "https://hosted.bugsink/api/1/envelope/",
            get_envelope_url("https://public_key@hosted.bugsink/1"))

    def test_get_header_value(self):
        self.assertEquals(
            "Sentry sentry_key=public_key, sentry_version=7, sentry_client=bugsink/0.0.1",
            get_header_value("https://public_key@hosted.bugsink/1"))

    def test_parse_header_value(self):
        self.assertEquals(
            {"sentry_key": "foo", "sentry_version": "bar"},
            parse_auth_header_value('Sentry sentry_key=foo,sentry_version=bar'))
