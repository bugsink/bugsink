import datetime
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from django.test.client import RequestFactory

from rest_framework.exceptions import ValidationError

from projects.models import Project
from events.factories import create_event_data
from issues.factories import get_or_create_issue
from issues.models import IssueStateManager, Issue
from bugsink.registry import reset_pc_registry

from .models import DecompressedEvent
from .views import BaseIngestAPIView


class IngestViewTestCase(TestCase):

    def setUp(self):
        # the existence of loud/quiet reflect that parts of this test focusses on alert-sending
        self.request_factory = RequestFactory()
        self.loud_project = Project.objects.create(
            name="loud",
            alert_on_new_issue=True,
            alert_on_regression=True,
            alert_on_unmute=True,
        )
        self.quiet_project = Project.objects.create(
            name="quiet",
            alert_on_new_issue=False,
            alert_on_regression=False,
            alert_on_unmute=False,
        )
        reset_pc_registry()  # see notes in issues/tests.py for possible improvement; needed because we test unmuting.

    def tearDown(self):
        reset_pc_registry()

    @patch("ingest.views.send_new_issue_alert")
    @patch("ingest.views.send_regression_alert")
    @patch("issues.models.send_unmute_alert")
    def test_ingest_view_new_issue_alert(self, send_unmute_alert, send_regression_alert, send_new_issue_alert):
        request = self.request_factory.post("/api/1/store/")

        BaseIngestAPIView().process_event(
            create_event_data(),
            self.loud_project,
            request,
        )
        self.assertTrue(send_new_issue_alert.delay.called)
        self.assertFalse(send_regression_alert.delay.called)
        self.assertFalse(send_unmute_alert.delay.called)

    @patch("ingest.views.send_new_issue_alert")
    @patch("ingest.views.send_regression_alert")
    @patch("issues.models.send_unmute_alert")
    def test_ingest_view_regression_alert(self, send_unmute_alert, send_regression_alert, send_new_issue_alert):
        event_data = create_event_data()

        issue, _ = get_or_create_issue(self.loud_project, event_data)
        issue.is_resolved = True
        issue.save()

        request = self.request_factory.post("/api/1/store/")

        BaseIngestAPIView().process_event(
            event_data,
            self.loud_project,
            request,
        )
        self.assertFalse(send_new_issue_alert.delay.called)
        self.assertTrue(send_regression_alert.delay.called)
        self.assertFalse(send_unmute_alert.delay.called)

    @patch("ingest.views.send_new_issue_alert")
    @patch("ingest.views.send_regression_alert")
    @patch("issues.models.send_unmute_alert")
    def test_ingest_view_funny_state(self, send_unmute_alert, send_regression_alert, send_new_issue_alert):
        # "funny", because we build an issue with a funny state (muted, resolved) on purpose to check that only a
        # regression alert is sent.
        event_data = create_event_data()

        issue, _ = get_or_create_issue(self.loud_project, event_data)

        # creation of the funny state:
        IssueStateManager.mute(issue, "[{\"period\": \"day\", \"nr_of_periods\": 1, \"volume\": 1}]")
        issue.is_resolved = True  # by setting this manually, we avoid the state-sanitizer code in IssueStateManager
        issue.save()

        request = self.request_factory.post("/api/1/store/")

        BaseIngestAPIView().process_event(
            event_data,
            self.loud_project,
            request,
        )
        self.assertFalse(send_new_issue_alert.delay.called)
        self.assertTrue(send_regression_alert.delay.called)
        self.assertFalse(send_unmute_alert.delay.called)

    @patch("ingest.views.send_new_issue_alert")
    @patch("ingest.views.send_regression_alert")
    @patch("issues.models.send_unmute_alert")
    def test_ingest_view_unmute_alert_for_vbc(self, send_unmute_alert, send_regression_alert, send_new_issue_alert):
        event_data = create_event_data()

        issue, _ = get_or_create_issue(self.loud_project, event_data)

        IssueStateManager.mute(issue, "[{\"period\": \"day\", \"nr_of_periods\": 1, \"volume\": 1}]")
        issue.save()

        request = self.request_factory.post("/api/1/store/")

        BaseIngestAPIView().process_event(
            event_data,
            self.loud_project,
            request,
        )
        self.assertFalse(send_new_issue_alert.delay.called)
        self.assertFalse(send_regression_alert.delay.called)
        self.assertTrue(send_unmute_alert.delay.called)

    @patch("ingest.views.send_new_issue_alert")
    @patch("ingest.views.send_regression_alert")
    @patch("issues.models.send_unmute_alert")
    def test_ingest_view_unmute_alert_after_time(self, send_unmute_alert, send_regression_alert, send_new_issue_alert):
        event_data = create_event_data()

        issue, _ = get_or_create_issue(self.loud_project, event_data)

        IssueStateManager.mute(issue, unmute_after_tuple=(1, "day"))
        issue.save()

        request = self.request_factory.post("/api/1/store/")

        BaseIngestAPIView().process_event(
            event_data,
            self.loud_project,
            request,
            now=timezone.now() + datetime.timedelta(days=2),
        )
        self.assertFalse(send_new_issue_alert.delay.called)
        self.assertFalse(send_regression_alert.delay.called)
        self.assertTrue(send_unmute_alert.delay.called)

    @patch("ingest.views.send_new_issue_alert")
    @patch("ingest.views.send_regression_alert")
    @patch("issues.models.send_unmute_alert")
    def test_ingest_view_no_alerts(self, send_unmute_alert, send_regression_alert, send_new_issue_alert):
        request = self.request_factory.post("/api/1/store/")

        # the thing we want to test here is "are no alerts sent when alerting is turned off"; but to make sure our test
        # doesn't silently break we've included the positive case in the loop here.
        for (expected_called, project) in [(False, self.quiet_project), (True, self.loud_project)]:
            # new event
            BaseIngestAPIView().process_event(
                create_event_data(),
                project,
                request,
            )
            self.assertEquals(expected_called, send_new_issue_alert.delay.called)

            issue = Issue.objects.get(project=project)
            issue.is_resolved = True
            issue.save()

            # regression
            BaseIngestAPIView().process_event(
                create_event_data(),
                project,
                request,
            )

            self.assertEquals(expected_called, send_regression_alert.delay.called)

            # mute
            issue = Issue.objects.get(project=project)
            IssueStateManager.mute(issue, "[{\"period\": \"day\", \"nr_of_periods\": 1, \"volume\": 3}]")
            issue.save()

            # unmute via API
            BaseIngestAPIView().process_event(
                create_event_data(),
                project,
                request,
            )
            self.assertEquals(expected_called, send_unmute_alert.delay.called)

    def test_deal_with_double_event_ids(self):
        request = self.request_factory.post("/api/1/store/")

        project = self.quiet_project

        event_data = create_event_data()

        # first time
        BaseIngestAPIView().process_event(
            event_data,
            project,
            request,
        )

        with self.assertRaises(ValidationError):
            # second time
            BaseIngestAPIView().process_event(
                event_data,
                project,
                request,
            )


class TimeZoneTesCase(TestCase):
    """This class contains some tests that formalize my understanding of how Django works; they are not strictly tests
    of bugsink code.

    We put this in events/tests.py because that's a place where we use Django's TestCase, and we want to test in that
    context, as well as the one of Event models.
    """

    def test_datetimes_are_in_utc_when_retrieved_from_the_database_with_default_conf(self):
        # check our default conf
        self.assertEquals("UTC", settings.TIME_ZONE)

        # save an event in the database; it will be saved in UTC (because that's what Django does)
        e = DecompressedEvent.objects.create()

        # we activate a timezone that is not UTC to ensure our tests run even when we're in a different timezone
        with timezone.override('America/Chicago'):
            self.assertEquals(datetime.timezone.utc, e.timestamp.tzinfo)

    def test_datetimes_are_in_utc_when_retrieved_from_the_database_no_matter_the_active_timezone_when_creating(self):
        with timezone.override('America/Chicago'):
            # save an event in the database; it will be saved in UTC (because that's what Django does); even when a
            # different timezone is active
            e = DecompressedEvent.objects.create()
            self.assertEquals(datetime.timezone.utc, e.timestamp.tzinfo)
