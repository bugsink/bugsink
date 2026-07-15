from django.test import TestCase as DjangoTestCase

from issues.grouping_mechanisms import BUGSINK_GROUPING_V1
from issues.utils import get_issue_grouper_for_data as _get_issue_grouper_for_data


def get_issue_grouper_for_data(data):
    return _get_issue_grouper_for_data(data, grouping_mechanism=BUGSINK_GROUPING_V1)


class GroupingV1TestCase(DjangoTestCase):

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

    def test_empty_data(self):
        self.assertEqual("Log Message: <no log message> ⋄ <no transaction>", get_issue_grouper_for_data({}))

    def test_logentry_message_takes_precedence(self):
        self.assertEqual("Log Message: msg: ? ⋄ <no transaction>", get_issue_grouper_for_data({"logentry": {
            "message": "msg: ?",
            "formatted": "msg: foobar",
        }}))

    def test_logentry_with_formatted_only(self):
        self.assertEqual("Log Message: msg: foobar ⋄ <no transaction>", get_issue_grouper_for_data({"logentry": {
            "formatted": "msg: foobar",
        }}))

    def test_logentry_with_transaction(self):
        self.assertEqual("Log Message: msg ⋄ transaction", get_issue_grouper_for_data({
            "logentry": {
                "message": "msg",
            },
            "transaction": "transaction",
        }))

    def test_exception_empty_trace(self):
        self.assertEqual("<unknown> ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [],
        }}))

    def test_exception_trace_no_data(self):
        self.assertEqual("<unknown> ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{}],
        }}))

    def test_exception_value_only(self):
        self.assertEqual("Error: exception message ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{"value": "exception message"}],
        }}))

    def test_exception_type_only(self):
        self.assertEqual("KeyError ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{"type": "KeyError"}],
        }}))

    def test_exception_type_value(self):
        self.assertEqual("KeyError: exception message ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{"type": "KeyError", "value": "exception message"}],
        }}))

    def test_exception_multiple_frames(self):
        self.assertEqual("KeyError: exception message ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{}, {}, {}, {"type": "KeyError", "value": "exception message"}],
        }}))

    def test_exception_transaction(self):
        self.assertEqual("KeyError ⋄ transaction", get_issue_grouper_for_data({
            "transaction": "transaction",
            "exception": {
                "values": [{"type": "KeyError"}],
            }
        }))

    def test_exception_function_is_ignored_unless_specifically_synthetic(self):
        # I make no value-judgement here on whether this is something we want to replicate in the future; as it stands
        # this test just documents the somewhat surprising behavior that we inherited from GlitchTip/Sentry.
        self.assertEqual("Error ⋄ <no transaction>", get_issue_grouper_for_data({
            "exception": {
                "values": [{
                    "stacktrace": {
                        "frames": [{"function": "foo"}],
                    },
                }],
            },
        }))

    def test_synthetic_exception_only(self):
        self.assertEqual("<unknown> ⋄ <no transaction>", get_issue_grouper_for_data({
            "exception": {
                "values": [{
                    "mechanism": {"synthetic": True},
                }],
            },
        }))

    def test_synthetic_exception_ignores_value(self):
        self.assertEqual("<unknown> ⋄ <no transaction>", get_issue_grouper_for_data({
            "exception": {
                "values": [{
                    "mechanism": {"synthetic": True},
                    "value": "the ignored value",
                }],
            },
        }))

    def test_exception_uses_function_when_top_level_exception_is_synthetic(self):
        self.assertEqual("foo ⋄ <no transaction>", get_issue_grouper_for_data({
            "exception": {
                "values": [{
                    "mechanism": {"synthetic": True},
                    "stacktrace": {
                        "frames": [{"function": "foo"}],
                    },
                }],
            },
        }))

    def test_exception_with_non_string_value(self):
        # In the GlitchTip code there is a mention of value sometimes containing a non-string value. Whether this
        # happens in practice is unknown to me, but let's build something that can handle it.
        self.assertEqual("KeyError: 123 ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{"type": "KeyError", "value": 123}],
        }}))

    def test_simple_fingerprint(self):
        self.assertEqual("fixed string", get_issue_grouper_for_data({"fingerprint": ["fixed string"]}))

    def test_fingerprint_with_default(self):
        self.assertEqual("Log Message: <no log message> ⋄ <no transaction> ⋄ fixed string",
                         get_issue_grouper_for_data({"fingerprint": ["{{ default }}", "fixed string"]}))
