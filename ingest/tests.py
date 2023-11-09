from django.test import TestCase

from sentry.utils.auth import parse_auth_header


class UtilsTestCase(TestCase):
    def test_parse_header(self):
        self.assertEquals(
            {"sentry_key": "foo", "sentry_version": "bar"},
            parse_auth_header('Sentry sentry_key=foo,sentry_version=bar'))
