from unittest import TestCase
import logging

from sentry_sdk_extensions import capture_or_log_exception

logger = logging.getLogger("test_logger")


class SentrySDKExtensionsTest(TestCase):

    def test_capture_or_log_exception(self):
        with self.assertLogs(logger='test_logger', level='ERROR') as test_logger_cm:
            try:
                raise Exception("I failed")
            except Exception as e:
                # in tests, the sentry SDK is off, so this tests the "or log exception" part of the test.
                capture_or_log_exception(e, logger)

                self.assertTrue('ERROR:test_logger:    raise Exception("I failed")' in test_logger_cm.output)
                self.assertTrue('ERROR:test_logger:Exception: I failed' in test_logger_cm.output)
