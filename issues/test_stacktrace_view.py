import json
import os
from pathlib import Path

from django.contrib.auth import get_user_model

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from events.factories import create_event
from projects.models import Project, ProjectMembership


SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", "../event-samples"))


def load_sample(relative_path):
    with open(SAMPLES_DIR / relative_path) as sample:
        return json.load(sample)


class StacktraceViewTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="test")
        self.project = Project.objects.create(name="Stacktrace view tests")
        ProjectMembership.objects.create(project=self.project, user=self.user, accepted=True)
        self.client.force_login(self.user)

    def render_stacktrace(self, event_data):
        event = create_event(
            project=self.project,
            event_data=event_data,
            platform=event_data["platform"],
        )
        return self.client.get(f"/issues/issue/{event.issue.id}/event/{event.id}/")

    def test_event_without_stacktrace_says_none_is_available(self):
        response = self.render_stacktrace({
            "platform": "python",
        })

        self.assertContains(response, "No stacktrace available for this event.")

    def test_exception_displays_type_and_value(self):
        response = self.render_stacktrace({
            "platform": "python",
            "exception": {
                "values": [{
                    "type": "ExampleError",
                    "value": "Something went wrong",
                }],
            },
        })

        self.assertContains(response, "ExampleError")
        self.assertContains(response, "Something went wrong")

    def test_frame_displays_location(self):
        response = self.render_stacktrace({
            "platform": "python",
            "exception": {
                "values": [{
                    "type": "ExampleError",
                    "value": "Something went wrong",
                    "stacktrace": {
                        "frames": [{
                            "filename": "example.py",
                            "function": "do_work",
                            "lineno": 421337,
                            "in_app": True,
                        }],
                    },
                }],
            },
        })

        self.assertContains(response, "example.py")
        self.assertContains(response, "do_work")
        self.assertContains(response, "421337")

    def test_python_frames_are_displayed_in_payload_order(self):
        response = self.render_stacktrace({
            "platform": "python",
            "exception": {
                "values": [{
                    "type": "ExampleError",
                    "value": "Something went wrong",
                    "stacktrace": {
                        "frames": [
                            {"filename": "call_started.py"},
                            {"filename": "error_raised.py"},
                        ],
                    },
                }],
            },
        })

        content = response.content.decode()
        self.assertLess(content.index("call_started.py"), content.index("error_raised.py"))

    def test_non_python_frames_are_displayed_in_reverse_payload_order(self):
        response = self.render_stacktrace({
            "platform": "java",
            "exception": {
                "values": [{
                    "type": "ExampleError",
                    "value": "Something went wrong",
                    "stacktrace": {
                        "frames": [
                            {"filename": "CallStarted.java"},
                            {"filename": "ErrorRaised.java"},
                        ],
                    },
                }],
            },
        })

        content = response.content.decode()
        self.assertLess(content.index("ErrorRaised.java"), content.index("CallStarted.java"))

    def test_exception_stacktrace_marks_beginning_and_raise(self):
        response = self.render_stacktrace({
            "platform": "python",
            "exception": {
                "values": [{
                    "type": "ExampleError",
                    "value": "Something went wrong",
                    "stacktrace": {
                        "frames": [
                            {"filename": "call_started.py"},
                            {"filename": "error_raised.py"},
                        ],
                    },
                }],
            },
        })

        content = response.content.decode()
        positions = [
            content.index("call_started.py"),
            content.index("\u2192 begin"),

            content.index("error_raised.py"),
            content.index("raise ExampleError"),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_handled_exception_stacktrace_marks_try_and_handled_raise(self):
        response = self.render_stacktrace({
            "platform": "python",
            "exception": {
                "values": [
                    {
                        "type": "HandledError",
                        "value": "The first failure",
                        "stacktrace": {
                            "frames": [
                                {"filename": "handled_call.py"},
                                {"filename": "handled_raise.py"},
                            ],
                        },
                    },
                    {
                        "type": "FinalError",
                        "value": "The second failure",
                        "stacktrace": {
                            "frames": [
                                {"filename": "final_call.py"},
                                {"filename": "final_raise.py"},
                            ],
                        },
                    },
                ],
            },
        })

        content = response.content.decode()
        positions = [
            content.index("handled_call.py"),
            content.index("try\u2026"),

            content.index("handled_raise.py"),
            content.index("raise HandledError (handled)"),

            content.index("final_call.py"),
            content.index("\u2192 begin"),

            content.index("final_raise.py"),
            content.index("raise FinalError"),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_python_exception_chain_is_displayed_in_payload_order(self):
        response = self.render_stacktrace({
            "platform": "python",
            "exception": {
                "values": [
                    {
                        "type": "HandledError",
                        "value": "The first failure",
                    },
                    {
                        "type": "FinalError",
                        "value": "The second failure",
                    },
                ],
            },
        })

        content = response.content.decode()
        separator = "During handling of the above exception another exception occurred or was intentionally reraised:"
        self.assertLess(content.index("The first failure"), content.index(separator))
        self.assertLess(content.index(separator), content.index("The second failure"))

    def test_non_python_exception_chain_is_displayed_in_reverse_payload_order(self):
        # Less realistic than a Java sample, but identical inputs make the ordering difference easier to inspect.
        response = self.render_stacktrace({
            "platform": "java",
            "exception": {
                "values": [
                    {
                        "type": "HandledError",
                        "value": "The first failure",
                    },
                    {
                        "type": "FinalError",
                        "value": "The second failure",
                    },
                ],
            },
        })

        content = response.content.decode()
        separator = (
            "The above exception was caused by or intentially reraised during the handling of the following exception:"
        )
        self.assertLess(content.index("The second failure"), content.index(separator))
        self.assertLess(content.index(separator), content.index("The first failure"))
