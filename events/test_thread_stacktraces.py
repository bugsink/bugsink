import json
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from rest_framework.test import APIClient

from bsmain.models import AuthToken
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project, ProjectMembership

from .factories import create_event
from .markdown_stacktrace import render_stacktrace_md
from .serializers import EventDetailSerializer
from .utils import get_stacktrace_entries


SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", "../event-samples"))
GENERATED_SAMPLES_DIR = SAMPLES_DIR / "generated"

THREAD_STACKTRACE_SAMPLES = [
    (
        "sentry-python-capture-message-attach-stacktrace.json",
        "capture_message attach_stacktrace from probe_capture_message.py",
        "probe_capture_message.py",
    ),
    (
        "sentry-python-logger-error-attach-stacktrace.json",
        "plain logger.error attach_stacktrace from probe_logger_error.py",
        "probe_logger_error.py",
    ),
    (
        "sentry-python-logger-error-stack-info.json",
        "logger.error stack_info from probe_logger_error_stack_info.py",
        "probe_logger_error_stack_info.py",
    ),
]

JAVA_MULTIPLE_THREADS_SAMPLE = "sentry-java-capture-message-attach-threads.json"
JAVA_MULTIPLE_THREADS_MESSAGE = "capture_message with all Java threads from ProbeMultipleThreads.java"


def load_generated_sample(filename):
    with open(GENERATED_SAMPLES_DIR / filename) as sample:
        return json.load(sample)


@tag("samples")
class ThreadStacktraceSampleTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="test")
        self.project = Project.objects.create(name="Thread stacktrace samples")
        ProjectMembership.objects.create(project=self.project, user=self.user, accepted=True)
        self.client.force_login(self.user)
        self.api_client = APIClient()
        token = AuthToken.objects.create()
        self.api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

    def test_capture_exception_uses_its_exception_stacktrace(self):
        data = load_generated_sample("sentry-python-capture-exception-add-full-stack.json")

        entries = get_stacktrace_entries(data)

        self.assertEqual(1, len(entries))
        self.assertEqual("RuntimeError", entries[0]["type"])
        self.assertTrue(entries[0]["is_exception_stacktrace"])
        self.assertEqual(3, len(entries[0]["stacktrace"]["frames"]))

    def test_thread_stacktrace_samples_render_the_log_message(self):
        for filename, message, probe_filename in THREAD_STACKTRACE_SAMPLES:
            with self.subTest(filename=filename):
                data = load_generated_sample(filename)
                event = create_event(project=self.project, event_data=data, platform=data["platform"])

                entries = get_stacktrace_entries(data)
                self.assertEqual(1, len(entries))
                self.assertEqual("Log Message", entries[0]["type"])
                self.assertEqual(message, entries[0]["value"])
                self.assertFalse(entries[0]["is_exception_stacktrace"])

                response = self.client.get(f"/issues/issue/{event.issue.id}/event/{event.id}/")
                self.assertContains(response, "Log Message")
                self.assertContains(response, message)
                self.assertContains(response, probe_filename)
                self.assertNotContains(response, "capture point")
                self.assertNotContains(response, "raise Log Message")
                self.assertNotContains(response, "\u2192 begin")
                self.assertNotContains(response, "Thread 1")
                self.assertNotContains(response, "No stacktrace available for this event.")

                markdown = render_stacktrace_md(event)
                self.assertIn("# Log Message", markdown)
                self.assertIn(message, markdown)
                self.assertIn(probe_filename, markdown)
                self.assertNotIn("Thread 1", markdown)
                self.assertNotEqual("_No stacktrace available._", markdown)

                detail = EventDetailSerializer(event).data
                self.assertEqual(markdown, detail["stacktrace_md"])

                response = self.api_client.get(reverse("api:event-detail", args=[event.id]))
                self.assertEqual(200, response.status_code)
                self.assertEqual(markdown, response.json()["stacktrace_md"])

                response = self.api_client.get(reverse("api:event-stacktrace", args=[event.id]))
                self.assertEqual(200, response.status_code)
                self.assertEqual(markdown, response.content.decode())

    def test_multiple_threads_render_the_first_stacktrace_with_frames(self):
        data = load_generated_sample(JAVA_MULTIPLE_THREADS_SAMPLE)
        event = create_event(project=self.project, event_data=data, platform=data["platform"])

        entries = get_stacktrace_entries(data)
        self.assertEqual(1, len(entries))
        self.assertEqual(data["threads"]["values"][1]["stacktrace"], entries[0]["stacktrace"])
        self.assertEqual("Log Message", entries[0]["type"])
        self.assertEqual(JAVA_MULTIPLE_THREADS_MESSAGE, entries[0]["value"])

        response = self.client.get(f"/issues/issue/{event.issue.id}/event/{event.id}/")
        self.assertContains(response, JAVA_MULTIPLE_THREADS_MESSAGE)
        self.assertContains(response, "ProbeMultipleThreads.java")
        self.assertNotContains(response, "bugsink-probe-background")
        self.assertNotContains(response, "No stacktrace available for this event.")

        markdown = render_stacktrace_md(event)
        self.assertIn(JAVA_MULTIPLE_THREADS_MESSAGE, markdown)
        self.assertIn("ProbeMultipleThreads.java", markdown)
        self.assertNotIn("bugsink-probe-background", markdown)
