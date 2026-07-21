from django.test import TestCase as DjangoTestCase

from issues.grouping_mechanisms import BUGSINK_GROUPING_V3
from issues.utils import get_grouping_result_for_data


def stacktrace_event_data(library_in_app=None):
    library_frame = {
        "module": "django.core.management",
        "filename": "/venv/lib/python3.12/site-packages/django/core/management/__init__.py",
        "function": "execute",
        "context_line": "utility.execute()",
    }
    if library_in_app is not None:
        library_frame["in_app"] = library_in_app

    return {
        "platform": "python",
        "exception": {
            "values": [{
                "type": "CapturedStacktraceForGrouping",
                "value": "1234 kinds of frames",
                "stacktrace": {
                    "frames": [
                        library_frame,
                        {
                            "module": "__main__",
                            "filename": "manage.py",
                            "function": "main",
                            "context_line": "main()",
                        },
                    ],
                },
            }],
        },
    }


class GroupingV3TestCase(DjangoTestCase):

    def test_stacktrace_grouping_calculates_app_and_system_candidates(self):
        result = get_grouping_result_for_data(stacktrace_event_data(), grouping_mechanism=BUGSINK_GROUPING_V3)

        self.assertEqual(["app", "system"], [candidate.name for candidate in result.candidates])
        self.assertNotEqual(result.candidates[0].key, result.candidates[1].key)

        app_component = result.candidates[0].component
        stacktrace = app_component["values"][0]["values"][2]
        frames = stacktrace["values"]

        self.assertFalse(frames[0]["contributes"])
        self.assertIn("site-packages", frames[0]["hint"])
        self.assertTrue(frames[1]["contributes"])

    def test_system_candidate_is_stable_when_in_app_detection_changes(self):
        first = get_grouping_result_for_data(stacktrace_event_data(), grouping_mechanism=BUGSINK_GROUPING_V3)
        second = get_grouping_result_for_data(
            stacktrace_event_data(library_in_app=True),
            grouping_mechanism=BUGSINK_GROUPING_V3,
        )

        self.assertNotEqual(first.candidates[0].key, second.candidates[0].key)
        self.assertEqual(first.candidates[1].key, second.candidates[1].key)
        self.assertEqual(second.candidates[0].key, second.candidates[1].key)
