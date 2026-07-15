from django.test import TestCase as DjangoTestCase

from issues.grouping_mechanisms import BUGSINK_GROUPING_V2, MECHANISM_INDEPENDENT_GROUPING
from issues.utils import (
    get_issue_grouper_for_data as _get_issue_grouper_for_data,
    get_key_with_mechanism_for_data as _get_key_with_mechanism_for_data,
    get_title_for_exception_type_and_value,
    get_type_and_value_for_data,
)


def get_key_with_mechanism_for_data(data):
    return _get_key_with_mechanism_for_data(data, grouping_mechanism=BUGSINK_GROUPING_V2)


def get_issue_grouper_for_data(data):
    return _get_issue_grouper_for_data(data, grouping_mechanism=BUGSINK_GROUPING_V2)


class GroupingV2TestCase(DjangoTestCase):

    def _exception_event_data(self, exception_type, exception_value, fingerprint=None):
        data = {
            "exception": {
                "values": [{
                    "type": exception_type,
                    "value": exception_value,
                }],
            },
            "transaction": "transaction",
        }
        if fingerprint is not None:
            data["fingerprint"] = fingerprint
        return data

    def test_key_with_mechanism_for_explicit_fingerprint_is_mechanism_independent(self):
        key_with_mechanism = get_key_with_mechanism_for_data({"fingerprint": ["fixed string"]})

        self.assertEqual("fixed string", key_with_mechanism.key)
        self.assertEqual(MECHANISM_INDEPENDENT_GROUPING, key_with_mechanism.mechanism)

    def test_key_with_mechanism_for_default_fingerprint_uses_v2(self):
        key_with_mechanism = get_key_with_mechanism_for_data({"fingerprint": ["{{ default }}", "fixed string"]})

        self.assertEqual("Log Message: <no log message> ⋄ fixed string", key_with_mechanism.key)
        self.assertEqual(BUGSINK_GROUPING_V2, key_with_mechanism.mechanism)

    def test_v2_grouping_ignores_transaction(self):
        # this trivially tests that #441, "transaction should not be part of the grouping key", is fixed.
        first_data = self._exception_event_data("KeyError", "exception message")
        second_data = self._exception_event_data("KeyError", "exception message")
        second_data["transaction"] = "other-transaction"

        first_key = get_issue_grouper_for_data(first_data)
        second_key = get_issue_grouper_for_data(second_data)

        self.assertEqual("KeyError: exception message", first_key)
        self.assertEqual(first_key, second_key)

    def test_normalized_exception_values_have_stable_grouping_key(self):
        cases = [
            (
                "SlowConsumerError",
                "Cannot publish <Consumer object at 0x7fbb00112233>",
                "Cannot publish <Consumer object at 0x7fbb44556677>",
                "<hex>",
            ),
            (
                "DatabaseError",
                "DB::Exception: Memory limit exceeded, would use 81604378624 bytes, code: 241",
                "DB::Exception: Memory limit exceeded, would use 91604378624 bytes, code: 242",
                "<int>",
            ),
            (
                "OperationalError",
                "could not connect to some-host:5432",
                "could not connect to some-host:6543",
                "some-host:<int>",
            ),
            (
                "LookupError",
                "missing object 2eb7d3ba-4d15-4f9d-9a8f-b1ddf7f94b93",
                "missing object 358a94e6-7649-455e-bfd5-91ba0d50a8e2",
                "<uuid>",
            ),
            (
                "ValueError",
                "invalid record name='alice'",
                "invalid record name='bob'",
                "name=<quoted_str>",
            ),
            (
                "ConnectionError",
                "failed to call api1.example.com",
                "failed to call api2.example.com",
                "<hostname>",
            ),
            (
                "TimeoutError",
                "request took 123ms",
                "request took 456ms",
                "<duration>",
            ),
            (
                "SchedulerError",
                "job started at 12:34 PM",
                "job started at 1:23 PM",
                "<date>",
            ),
            (
                "ParseError",
                "bad header on Mon, 02 Jan 2006 15:04:05 GMT",
                "bad header on Tue, 03 Jan 2006 16:05:06 GMT",
                "<date>",
            ),
        ]

        for exception_type, first_value, second_value, expected_placeholder in cases:
            with self.subTest(exception_type=exception_type):
                first_data = self._exception_event_data(exception_type, first_value)
                second_data = self._exception_event_data(exception_type, second_value)

                first_key = get_issue_grouper_for_data(first_data)
                second_key = get_issue_grouper_for_data(second_data)

                self.assertEqual(first_key, second_key)
                self.assertIn(expected_placeholder, first_key)

    def test_normalized_exception_grouping_keeps_display_title_raw(self):
        value = "Cannot publish <Consumer object at 0x7fbb00112233>"
        data = self._exception_event_data("SlowConsumerError", value)

        grouping_key = get_issue_grouper_for_data(data)
        calculated_type, calculated_value = get_type_and_value_for_data(data)
        title = get_title_for_exception_type_and_value(calculated_type, calculated_value)

        self.assertIn("<hex>", grouping_key)
        self.assertEqual("SlowConsumerError: Cannot publish <Consumer object at 0x7fbb00112233>", title)

    def test_normalized_log_messages_have_stable_grouping_key_but_raw_title(self):
        first_data = {"logentry": {"message": "User 123 failed from 10.0.0.1"}}
        second_data = {"logentry": {"message": "User 456 failed from 10.0.0.2"}}

        first_key = get_issue_grouper_for_data(first_data)
        second_key = get_issue_grouper_for_data(second_data)
        calculated_type, calculated_value = get_type_and_value_for_data(first_data)
        title = get_title_for_exception_type_and_value(calculated_type, calculated_value)

        self.assertEqual(first_key, second_key)
        self.assertEqual("Log Message: User <int> failed from <ip>", first_key)
        self.assertEqual("Log Message: User 123 failed from 10.0.0.1", title)

    def test_normalized_exception_grouping_leaves_explicit_fingerprint_unchanged(self):
        data = self._exception_event_data(
            "SlowConsumerError",
            "Cannot publish <Consumer object at 0x7fbb00112233>",
            fingerprint=["fixed 0x7fbb00112233"],
        )

        self.assertEqual(
            "fixed 0x7fbb00112233",
            get_issue_grouper_for_data(data),
        )

    def test_normalized_exception_grouping_changes_default_fingerprint_expansion(self):
        first_data = self._exception_event_data(
            "SlowConsumerError",
            "Cannot publish <Consumer object at 0x7fbb00112233>",
            fingerprint=["{{ default }}", "fixed string"],
        )
        second_data = self._exception_event_data(
            "SlowConsumerError",
            "Cannot publish <Consumer object at 0x7fbb44556677>",
            fingerprint=["{{ default }}", "fixed string"],
        )

        first_key = get_issue_grouper_for_data(first_data)
        second_key = get_issue_grouper_for_data(second_data)

        self.assertEqual(first_key, second_key)
        self.assertIn("SlowConsumerError: Cannot publish <Consumer object at <hex>>", first_key)
        self.assertTrue(first_key.endswith(" ⋄ fixed string"))
