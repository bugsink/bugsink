import datetime

from django.test import TestCase as DjangoTestCase
from unittest import TestCase as RegularTestCase
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project, ProjectMembership
from issues.models import Issue
from issues.factories import denormalized_issue_fields

from .factories import create_event
from .retention import eviction_target

User = get_user_model()


class ViewTests(TransactionTestCase):
    # we start with minimal "does this show something and not fully crash" tests and will expand from there.

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', password='test')
        self.project = Project.objects.create()
        ProjectMembership.objects.create(project=self.project, user=self.user)
        self.issue = Issue.objects.create(project=self.project, **denormalized_issue_fields())
        self.event = create_event(self.project, self.issue)
        self.client.force_login(self.user)

    def test_event_download(self):
        response = self.client.get(f"/events/event/{self.event.pk}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertTrue("platform" in response.json())

    def test_event_raw(self):
        response = self.client.get(f"/events/event/{self.event.pk}/raw/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertTrue("platform" in response.json())

    def test_event_plaintext(self):
        response = self.client.get(f"/events/event/{self.event.pk}/plain/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')


class TimeZoneTestCase(DjangoTestCase):
    """This class contains some tests that formalize my understanding of how Django works; they are not strictly tests
    of bugsink code.

    We put this in events/tests.py because that's a place where we use Django's TestCase, and we want to test in that
    context, as well as the one of Event models.
    """

    def test_datetimes_are_in_utc_when_retrieved_from_the_database_with_default_conf(self):
        # check our default (test) conf
        self.assertEqual("Europe/Amsterdam", settings.TIME_ZONE)

        # save an event in the database; it will be saved in UTC (because that's what Django does)
        e = create_event()

        # we activate a timezone that is not UTC to ensure our tests run even when we're in a different timezone
        with timezone.override('America/Chicago'):
            self.assertEqual(datetime.timezone.utc, e.timestamp.tzinfo)

    def test_datetimes_are_in_utc_when_retrieved_from_the_database_no_matter_the_active_timezone_when_creating(self):
        with timezone.override('America/Chicago'):
            # save an event in the database; it will be saved in UTC (because that's what Django does); even when a
            # different timezone is active
            e = create_event()
            self.assertEqual(datetime.timezone.utc, e.timestamp.tzinfo)


class RetentionTestCase(RegularTestCase):
    def test_eviction_target(self):
        # over-target with low max: evict 5%
        self.assertEqual(5, eviction_target(100, 101))

        # over-target with high max: evict 500
        self.assertEqual(500, eviction_target(10_000, 10_001))
        self.assertEqual(500, eviction_target(100_000, 100_001))

        # adapted target, i.e. over target but by (much) more than 1: evict 500
        # (we chose this over the alternative of evicting all of the excess at once, because the latter could very well
        # lead to timeouts. this has the slightly surprising effect that eviction happens only in 500-event steps, and
        # because we don't trigger such steps unless new events come in, it could take a while to get back under target.
        # if this turns out to be a problem, we should just do that triggering ourselves rather than per-event).
        self.assertEqual(500, eviction_target(100, 10_001))

        # ridiciulously low max: evict 1
        self.assertEqual(1, eviction_target(6, 7))

        # Note that we have no special-casing for under-target (yet); not needed because should_evict (which does a
        # simple comparison) is always called first.
        # self.assertEqual(0, eviction_target(10_000, 9_999))
