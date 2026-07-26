from django.contrib.auth import get_user_model

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from events.factories import create_event
from projects.models import Project, ProjectMembership


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
