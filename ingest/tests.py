from glob import glob
import json
import io
import uuid
import time

import datetime
from unittest.mock import patch
from unittest import TestCase as RegularTestCase

from django.test import TransactionTestCase
from django.utils import timezone
from django.test.client import RequestFactory
from django.core.exceptions import ValidationError

from projects.models import Project
from events.factories import create_event_data
from issues.factories import get_or_create_issue
from issues.models import IssueStateManager, Issue, TurningPoint, TurningPointKind
from bugsink.registry import reset_pc_registry
from compat.timestamp import format_timestamp
from compat.dsn import get_header_value
from ingest.management.commands.send_json import Command as SendJsonCommand

from .views import BaseIngestAPIView
from .parsers import readuntil, NewlineFinder, ParseError, LengthFinder, StreamingEnvelopeParser


def _digest_params(event_data, project, request, now=None):
    if now is None:
        # because we want to count events before having created event objects (quota may block the latter) we cannot
        # depend on event.timestamp; instead, we look on the clock once here, and then use that for both the project
        # and issue period counters.
        now = datetime.datetime.now(timezone.utc)

    # adapter to quickly reuse existing tests on refactored code. let's see where the code ends up before spending
    # considerable time on rewriting the tests
    return {
        "event_metadata": {"project_id": project.id, "timestamp": format_timestamp(now), "debug_info": ""},
        "event_data": event_data,
        "project": project,
    }


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

        BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), self.loud_project, request))

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

        BaseIngestAPIView().digest_event(**_digest_params(event_data, self.loud_project, request))

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

        BaseIngestAPIView().digest_event(**_digest_params(event_data, self.loud_project, request))

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

        BaseIngestAPIView().digest_event(**_digest_params(event_data, self.loud_project, request))

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

        BaseIngestAPIView().digest_event(**_digest_params(
            event_data,
            self.loud_project,
            request,
            now=timezone.now() + datetime.timedelta(days=2),
        ))
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
            BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), project, request))

            self.assertEquals(expected_called, send_new_issue_alert.delay.called)

            issue = Issue.objects.get(project=project)
            issue.is_resolved = True
            issue.save()

            # regression
            BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), project, request))

            self.assertEquals(expected_called, send_regression_alert.delay.called)

            # mute
            issue = Issue.objects.get(project=project)
            IssueStateManager.mute(issue, "[{\"period\": \"day\", \"nr_of_periods\": 1, \"volume\": 3}]")
            issue.save()

            # unmute via API
            BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), project, request))

            self.assertEquals(expected_called, send_unmute_alert.delay.called)

    def test_deal_with_double_event_ids(self):
        request = self.request_factory.post("/api/1/store/")

        project = self.quiet_project

        event_data = create_event_data()

        # first time
        BaseIngestAPIView().digest_event(**_digest_params(event_data, project, request))

        with self.assertRaises(ValidationError):
            # second time
            BaseIngestAPIView().digest_event(**_digest_params(event_data, project, request))

    def test_ingest_view_stores_events_at(self):
        request = self.request_factory.post("/api/1/store/")

        event_data = create_event_data()
        event_data["release"] = "1.0"

        BaseIngestAPIView().digest_event(**_digest_params(event_data, self.loud_project, request))

        self.assertEquals(1, Issue.objects.count())
        self.assertEquals("1.0\n", Issue.objects.get().events_at)

    def test_envelope_endpoint(self):
        # dirty copy/paste from the integration test, let's start with "something", we can always clean it later.
        project = Project.objects.create(name="test")

        sentry_auth_header = get_header_value(f"http://{ project.sentry_key }@hostisignored/{ project.id }")

        # first, we ingest many issues
        command = SendJsonCommand()
        command.stdout = io.StringIO()
        command.stderr = io.StringIO()

        for filename in glob("./ingest/samples/*/*.json")[:1]:  # one is enough here
            with open(filename) as f:
                data = json.loads(f.read())

            data["event_id"] = uuid.uuid4().hex

            if "timestamp" not in data:
                # as per send_json command ("weirdly enough a large numer of sentry test data don't actually...")
                data["timestamp"] = time.time()

            if not command.is_valid(data, filename):
                continue

            data_bytes = json.dumps(data).encode("utf-8")
            data_bytes = (b'{"event_id": "%s"}\n{"type": "event"}\n' % (data["event_id"]).encode("utf-8") + data_bytes)

            response = self.client.post(
                f"/api/{ project.id }/envelope/",
                content_type="application/json",
                headers={
                    "X-Sentry-Auth": sentry_auth_header,
                    "X-BugSink-DebugInfo": filename,
                },
                data=data_bytes,
            )
            self.assertEquals(
                200, response.status_code, response.content if response.status_code != 302 else response.url)


class TestParser(RegularTestCase):

    def test_readuntil_newline_everything_in_initial_chunk(self):
        input_stream = io.BytesIO(b"line 2\nline 3\n")
        initial_chunk = b"line 0\nline 1\n"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"line 1\n", remainder)
        self.assertEquals(b"line 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_with_initial_chunk(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"li", remainder)
        self.assertEquals(b"ne 1\nline 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_no_initial_chunk(self):
        input_stream = io.BytesIO(b"line 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b""
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"li", remainder)
        self.assertEquals(b"ne 1\nline 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_until_eof(self):
        input_stream = io.BytesIO(b"line 0")
        initial_chunk = b""
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 3)

        self.assertTrue(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"", remainder)
        self.assertEquals(b"", input_stream.read())

    def test_readuntil_newline_bigger_chunk(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 1024)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0", output_stream.getvalue())
        self.assertEquals(b"line 1\nline 2\nline 3\n", remainder)
        self.assertEquals(b"", input_stream.read())

    def test_readuntil_length(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, LengthFinder(10, "eof not ok"), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEquals(b"line 0\nlin", output_stream.getvalue())
        self.assertEquals(b"e ", remainder)
        self.assertEquals(b"1\nline 2\nline 3\n", input_stream.read())

    def test_readuntil_length_eof_is_exception(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        with self.assertRaises(ParseError):
            remainder, at_eof = readuntil(input_stream, initial_chunk, LengthFinder(100, "EOF"), output_stream, 1000)

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

        # > If length cannot be consumed, that is, the Envelope is EOF before the number of bytes has been consumed,
        # > then the Envelope is malformed.
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\n{"type":"event","length":42,"content_type":"application/json","filename":"application.log"}\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        with self.assertRaises(ParseError) as e:
            header, item = next(items)
        self.assertEquals("EOF while reading item with explicitly specified length", str(e.exception))

    def test_too_much_content_aka_length_too_short(self):
        # based on test_envelope_with_2_items_last_newline_omitted, but with length "41" replaced by "40"

        # > Length-prefixed payloads must terminate with \n or EOF. The newline is not considered part of the payload.
        # > Any other character, including whitespace, means the Envelope is malformed.
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\n{"type":"event","length":40,"content_type":"application/json","filename":"application.log"}\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        with self.assertRaises(ParseError) as e:
            header, item = next(items)
        self.assertEquals("Item with explicit length not terminated by newline/EOF", str(e.exception))

    def test_non_json_header(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\nTHIS IS NOT JSON\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        with self.assertRaises(ParseError) as e:
            header, item = next(items)
        self.assertEquals("Header not JSON", str(e.exception))

    def test_eof_after_envelope_headers(self):
        # whether this is valid or not: not entirely clear from the docs. It won't matter in practice, of course
        # (because nothing interesting is contained)
        # hints in the documentation that this is correct:
        # > Header-only Example:  <= this implies such an example might be seen in the wild
        # > There can be an arbitrary number of Items in an Envelope   <= 0 is an arbitrary number
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{}"""))

        items = parser.get_items_directly()
        with self.assertRaises(StopIteration):
            header, item = next(items)

    def test_eof_after_item_headers(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{}\n{}"""))

        items = parser.get_items_directly()

        with self.assertRaises(ParseError) as e:
            header, item = next(items)
        self.assertEquals("EOF when reading headers; what is this a header for then?", str(e.exception))

    def test_item_headers_but_no_item(self):
        # another edge case that we don't care about much (no data)
        # as per test_item_with_implicit_length_last_newline_omitted_terminated_by_eof, "implicit lenght and last
        # newline omitted" is a valid combination. We make explicit that this is also the case for 0-length item
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{}\n{}\n"""))

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEquals(b"", item)

        with self.assertRaises(StopIteration):
            header, item = next(items)
