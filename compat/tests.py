import json
from unittest import TestCase as RegularTestCase
import datetime
from django.test import override_settings

from .dsn import build_dsn, get_store_url, get_envelope_url, get_header_value
from .auth import parse_auth_header_value
from .timestamp import parse_timestamp
from .vars import unrepr


class DsnTestCase(RegularTestCase):
    def test_build_dsn(self):
        self.assertEqual(
            "https://public_key@hosted.bugsink/1",
            build_dsn("https://hosted.bugsink", "1", "public_key"))

        self.assertEqual(
            "https://public_key@hosted.bugsink/foo/1",
            build_dsn("https://hosted.bugsink/foo", "1", "public_key"))

    def test_build_dsn_non_default_port(self):
        self.assertEqual(
            "https://public_key@hosted.bugsink:8000/1",
            build_dsn("https://hosted.bugsink:8000", "1", "public_key"))

    def test_get_store_url(self):
        self.assertEqual(
            "https://hosted.bugsink/api/1/store/",
            get_store_url("https://public_key@hosted.bugsink/1"))

        self.assertEqual(
            "https://hosted.bugsink/some/path/api/1/store/",
            get_store_url("https://public_key@hosted.bugsink/some/path/1"))

    def test_get_store_url_non_default_port(self):
        self.assertEqual(
            "http://hosted.bugsink:8000/api/1/store/",
            get_store_url("http://public_key@hosted.bugsink:8000/1"))

    def test_get_envelope_url(self):
        self.assertEqual(
            "https://hosted.bugsink/api/1/envelope/",
            get_envelope_url("https://public_key@hosted.bugsink/1"))

    def test_get_header_value(self):
        self.assertEqual(
            "Sentry sentry_key=public_key, sentry_version=7, sentry_client=bugsink/0.0.1",
            get_header_value("https://public_key@hosted.bugsink/1"))


class AuthTestCase(RegularTestCase):
    def test_parse_header_value(self):
        self.assertEqual(
            {"sentry_key": "foo", "sentry_version": "bar"},
            parse_auth_header_value('Sentry sentry_key=foo,sentry_version=bar'))


class TimestampTestCase(RegularTestCase):
    def test_numeric_values(self):
        self.assertEqual(
            datetime.datetime(2023, 11, 11, 17, 32, 24, tzinfo=datetime.timezone.utc),
            parse_timestamp(1699723944))

        self.assertEqual(
            datetime.datetime(2023, 11, 11, 17, 32, 24, 500_000, tzinfo=datetime.timezone.utc),
            parse_timestamp(1699723944.5))

    def test_string(self):
        self.assertEqual(
            datetime.datetime(2022, 9, 1, 9, 45, 0, tzinfo=datetime.timezone.utc),
            parse_timestamp("2022-09-01T09:45:00.000Z"))

        self.assertEqual(
            datetime.datetime(2018, 1, 1, 5, 6, 7, tzinfo=datetime.timezone.utc),
            parse_timestamp("2018-01-01T05:06:07+00:00"))

    @override_settings(TIME_ZONE='Europe/Istanbul')
    def test_non_utc_settings_dont_influence_parsing(self):
        self.assertEqual(
            datetime.datetime(2023, 11, 11, 17, 32, 24, tzinfo=datetime.timezone.utc),
            parse_timestamp(1699723944))

        self.assertEqual(
            datetime.datetime(2022, 9, 1, 9, 45, 0, tzinfo=datetime.timezone.utc),
            parse_timestamp("2022-09-01T09:45:00.000Z"))


class VarsTestCase(RegularTestCase):
    def test_dicts(self):
        d = json.loads('''{"baz":"1","foo":"'bar'","snu":"None","recurse":{"foo": "'bar'"}}''')

        self.assertEqual(
            '''{baz: 1, foo: 'bar', snu: None, recurse: {foo: 'bar'}}''',
            unrepr(d))

    def test_lists(self):
        d = json.loads('''["'bar'","1","None",["'bar'","1","None"]]''')

        self.assertEqual(
            '''['bar', 1, None, ['bar', 1, None]]''',
            unrepr(d))
