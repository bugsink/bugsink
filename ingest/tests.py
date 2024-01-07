import datetime

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from django.test.client import RequestFactory

from projects.models import Project
from events.factories import create_event_data

from .models import DecompressedEvent
from .views import BaseIngestAPIView


class IngestViewTestCase(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def test_ingest_view(self):
        project = Project.objects.create(name="test")
        request = self.factory.post("/api/1/store/")

        BaseIngestAPIView().process_event(
            create_event_data(),
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
