from unittest import TestCase
import datetime
from django.test import override_settings

from .dsn import get_store_url, get_envelope_url, get_header_value
from .auth import parse_auth_header_value
from .timestamp import parse_timestamp


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


class AuthTestCase(TestCase):
    def test_parse_header_value(self):
        self.assertEquals(
            {"sentry_key": "foo", "sentry_version": "bar"},
            parse_auth_header_value('Sentry sentry_key=foo,sentry_version=bar'))


class TimestampTestCase(TestCase):
    def test_numeric_values(self):
        self.assertEquals(
            datetime.datetime(2023, 11, 11, 17, 32, 24, tzinfo=datetime.timezone.utc),
            parse_timestamp(1699723944))

        self.assertEquals(
            datetime.datetime(2023, 11, 11, 17, 32, 24, 500_000, tzinfo=datetime.timezone.utc),
            parse_timestamp(1699723944.5))

    def test_string(self):
        self.assertEquals(
            datetime.datetime(2022, 9, 1, 9, 45, 0, tzinfo=datetime.timezone.utc),
            parse_timestamp("2022-09-01T09:45:00.000Z"))

        self.assertEquals(
            datetime.datetime(2018, 1, 1, 5, 6, 7, tzinfo=datetime.timezone.utc),
            parse_timestamp("2018-01-01T05:06:07+00:00"))

    @override_settings(TIME_ZONE='Europe/Istanbul')
    def test_non_utc_settings_dont_influence_parsing(self):
        self.assertEquals(
            datetime.datetime(2023, 11, 11, 17, 32, 24, tzinfo=datetime.timezone.utc),
            parse_timestamp(1699723944))

        self.assertEquals(
            datetime.datetime(2022, 9, 1, 9, 45, 0, tzinfo=datetime.timezone.utc),
            parse_timestamp("2022-09-01T09:45:00.000Z"))
