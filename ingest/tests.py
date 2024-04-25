import io

import datetime
from unittest.mock import patch
from unittest import TestCase as RegularTestCase

from django.conf import settings
from django.test import TestCase as DjangoTestCase, TransactionTestCase
from django.utils import timezone
from django.test.client import RequestFactory

from rest_framework.exceptions import ValidationError

from projects.models import Project
from events.factories import create_event_data
from issues.factories import get_or_create_issue
from issues.models import IssueStateManager, Issue, TurningPoint, TurningPointKind
from bugsink.registry import reset_pc_registry

from .models import DecompressedEvent
from .views import BaseIngestAPIView
from .parsers import readuntil, NewlineFinder, ParseError, LengthFinder, StreamingEnvelopeParser


class IngestViewTestCase(TransactionTestCase):
    # this TestCase started out as focussed on alert-sending, but has grown beyond that. Sometimes simply by extending
    # existing tests. This is not a problem in itself, but may be slightly confusing if you don't realize that.

    # We use TransactionTestCase because of the following:
    #
    # > Django’s TestCase class wraps each test in a transaction and rolls back that transaction after each test, in
    # > order to provide test isolation. This means that no transaction is ever actually committed, thus your
    # > on_commit() callbacks will never be run.
    # > [..]
    # > Another way to overcome the limitation is to use TransactionTestCase instead of TestCase. This will mean your
    # > transactions are committed, and the callbacks will run. However [..] significantly slower [..]

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
        self.assertEquals(1, Issue.objects.count())
        self.assertEquals("\n", Issue.objects.get().events_at)
        self.assertEquals(1, TurningPoint.objects.count())
        self.assertEquals(TurningPointKind.FIRST_SEEN, TurningPoint.objects.first().kind)

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
        self.assertEquals(1, TurningPoint.objects.count())
        self.assertEquals(TurningPointKind.REGRESSED, TurningPoint.objects.first().kind)

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
        self.assertEquals(1, TurningPoint.objects.count())
        self.assertEquals(TurningPointKind.REGRESSED, TurningPoint.objects.first().kind)

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
        self.assertEquals(1, TurningPoint.objects.count())
        self.assertEquals(TurningPointKind.UNMUTED, TurningPoint.objects.first().kind)
        self.assertEquals(send_unmute_alert.delay.call_args[0][0], str(issue.id))
        self.assertEquals(
            send_unmute_alert.delay.call_args[0][1], "More than 1 events per 1 day occurred, unmuting the issue.")

    @patch("ingest.views.send_new_issue_alert")
    @patch("ingest.views.send_regression_alert")
    @patch("issues.models.send_unmute_alert")
    def test_ingest_view_unmute_alert_after_time(self, send_unmute_alert, send_regression_alert, send_new_issue_alert):
        event_data = create_event_data()

        issue, _ = get_or_create_issue(self.loud_project, event_data)

        IssueStateManager.mute(issue, unmute_after=timezone.now() + datetime.timedelta(days=1))
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
        self.assertEquals(1, TurningPoint.objects.count())
        self.assertEquals(TurningPointKind.UNMUTED, TurningPoint.objects.first().kind)
        self.assertEquals(send_unmute_alert.delay.call_args[0][0], str(issue.id))
        self.assertTrue("An event was observed after the mute-deadline of" in send_unmute_alert.delay.call_args[0][1])

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

    def test_ingest_view_stores_events_at(self):
        request = self.request_factory.post("/api/1/store/")

        event_data = create_event_data()
        event_data["release"] = "1.0"

        BaseIngestAPIView().process_event(
            event_data,
            self.loud_project,
            request,
        )
        self.assertEquals(1, Issue.objects.count())
        self.assertEquals("1.0\n", Issue.objects.get().events_at)


class TimeZoneTesCase(DjangoTestCase):
    """This class contains some tests that formalize my understanding of how Django works; they are not strictly tests
    of bugsink code.

    We put this in events/tests.py because that's a place where we use Django's TestCase, and we want to test in that
    context, as well as the one of Event models.
    """

    def test_datetimes_are_in_utc_when_retrieved_from_the_database_with_default_conf(self):
        # check our default conf
        self.assertEquals("Europe/Amsterdam", settings.TIME_ZONE)

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


class TestParser(RegularTestCase):

    def test_readuntil_newline_everything_in_initial_chunk(self):
        input_stream = io.BytesIO(b"line 2\nline 3\n")
        initial_chunk = b"line 0\nline 1\n"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(None), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"line 1\n", remainder)
        self.assertEquals(b"line 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_with_initial_chunk(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(None), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"li", remainder)
        self.assertEquals(b"ne 1\nline 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_no_initial_chunk(self):
        input_stream = io.BytesIO(b"line 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b""
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(None), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"li", remainder)
        self.assertEquals(b"ne 1\nline 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_until_eof(self):
        input_stream = io.BytesIO(b"line 0")
        initial_chunk = b""
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(None), output_stream, 3)

        self.assertTrue(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"", remainder)
        self.assertEquals(b"", input_stream.read())

    def test_readuntil_newline_eof_is_exception(self):
        input_stream = io.BytesIO(b"line 0")
        initial_chunk = b""
        input_stream.seek(0)

        output_stream = io.BytesIO()
        with self.assertRaises(ParseError):
            remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder("eof not ok"), output_stream, 3)

    def test_readuntil_newline_bigger_chunk(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(None), output_stream, 1024)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"line 1\nline 2\nline 3\n", remainder)
        self.assertEquals(b"", input_stream.read())

    def test_readuntil_length(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, LengthFinder(10, None), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0\nlin", output_stream.getvalue())
        self.assertEquals(10, len(b"line 0\nlin"))  # this explains the previous line
        self.assertEquals(b"e ", remainder)
        self.assertEquals(b"1\nline 2\nline 3\n", input_stream.read())

    # The "full examples" below are from the Sentry developer documentation; we should at least be able to parse those

    def test_full_example_envelope_with_2_items(self):
        # Note that the attachment contains a Windows newline at the end of its
        # payload which is included in `length`:

        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\n{"type":"attachment","length":10,"content_type":"text/plain","filename":"hello.txt"}\n\xef\xbb\xbfHello\r\n\n{"type":"event","length":41,"content_type":"application/json","filename":"application.log"}\n{"message":"hello world","level":"error"}\n"""))  # noqa

        envelope_headers = parser.get_envelope_headers()
        self.assertEquals(
            {"event_id": "9ec79c33ec9942ab8353589fcb2e04dc",
             "dsn": "https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"},
            envelope_headers)

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEquals(
            {"type": "attachment", "length": 10, "content_type": "text/plain", "filename": "hello.txt"},
            header)  # we check item-header parsing once, should be enough.
        self.assertEquals(b"\xef\xbb\xbfHello\r\n", item)

        header, item = next(items)
        self.assertEquals(b'{"message":"hello world","level":"error"}', item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_envelope_with_2_items_last_newline_omitted(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\n{"type":"attachment","length":10,"content_type":"text/plain","filename":"hello.txt"}\n\xef\xbb\xbfHello\r\n\n{"type":"event","length":41,"content_type":"application/json","filename":"application.log"}\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEquals(b"\xef\xbb\xbfHello\r\n", item)

        header, item = next(items)
        self.assertEquals(b'{"message":"hello world","level":"error"}', item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_envelope_with_2_empty_attachments(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc"}\n{"type":"attachment","length":0}\n\n{"type":"attachment","length":0}\n\n"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEquals(b"", item)

        header, item = next(items)
        self.assertEquals(b"", item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_envelope_with_2_empty_attachments_last_newline_omitted(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc"}\n{"type":"attachment","length":0}\n\n{"type":"attachment","length":0}\n"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEquals(b"", item)

        header, item = next(items)
        self.assertEquals(b"", item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_item_with_implicit_length_terminated_by_newline(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc"}\n{"type":"attachment"}\nhelloworld\n"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEquals(b"helloworld", item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_item_with_implicit_length_last_newline_omitted_terminated_by_eof(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc"}\n{"type":"attachment"}\nhelloworld"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEquals(b"helloworld", item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_envelope_without_headers_implicit_length_last_newline_omitted_terminated_by_eof(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{}\n{"type":"session"}\n{"started": "2020-02-07T14:16:00Z","attrs":{"release":"sentry-test@1.0.0"}}"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEquals(b'{"started": "2020-02-07T14:16:00Z","attrs":{"release":"sentry-test@1.0.0"}}', item)

        with self.assertRaises(StopIteration):
            next(items)

    # Below: not from documenation, but inpsired by it

    def test_missing_content_aka_length_too_long(self):
        # based on test_envelope_with_2_items_last_newline_omitted, but with length "41" replaced by "42"
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\n{"type":"event","length":42,"content_type":"application/json","filename":"application.log"}\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        with self.assertRaises(ParseError) as e:
            header, item = next(items)
        self.assertEquals("EOF while reading item with explicitly specified length", str(e.exception))

    def test_non_json_header(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\nTHIS IS NOT JSON\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        with self.assertRaises(ParseError) as e:
            header, item = next(items)
        self.assertEquals("Header not JSON", str(e.exception))
