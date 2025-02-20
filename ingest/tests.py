import os
from glob import glob
import json
import io
import uuid
import time
import tempfile

import datetime
from unittest.mock import patch
from unittest import TestCase as RegularTestCase
from dateutil.relativedelta import relativedelta

from django.test import tag
from django.utils import timezone
from django.test.client import RequestFactory
from django.core.exceptions import ValidationError

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project
from events.factories import create_event_data, create_event
from events.retention import evict_for_max_events
from events.storage_registry import override_event_storages
from issues.factories import get_or_create_issue
from issues.models import IssueStateManager, Issue, TurningPoint, TurningPointKind
from bugsink.app_settings import override_settings
from compat.timestamp import format_timestamp
from compat.dsn import get_header_value
from bsmain.management.commands.send_json import Command as SendJsonCommand

from .views import BaseIngestAPIView
from .parsers import readuntil, NewlineFinder, ParseError, LengthFinder, StreamingEnvelopeParser
from .event_counter import check_for_thresholds
from bugsink.exceptions import ViolatedExpectation


def _digest_params(event_data, project, request, now=None):
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)

    # adapter to quickly reuse existing tests on refactored code. let's see where the code ends up before spending
    # considerable time on rewriting the tests
    return {
        "event_metadata": {
            "event_id": event_data["event_id"],
            "project_id": project.id,
            "ingested_at": format_timestamp(now),
            "debug_info": "",
        },
        "event_data": event_data,
        "digested_at": now,
    }


def _readlines(filename):
    with open(filename) as f:
        return f.readlines()


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
        super().setUp()

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

    @patch("ingest.views.send_new_issue_alert")
    @patch("ingest.views.send_regression_alert")
    @patch("issues.models.send_unmute_alert")
    def test_ingest_view_new_issue_alert(self, send_unmute_alert, send_regression_alert, send_new_issue_alert):
        request = self.request_factory.post("/api/1/store/")

        BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), self.loud_project, request))

        self.assertTrue(send_new_issue_alert.delay.called)
        self.assertFalse(send_regression_alert.delay.called)
        self.assertFalse(send_unmute_alert.delay.called)
        self.assertEqual(1, Issue.objects.count())
        self.assertEqual("\n", Issue.objects.get().events_at)
        self.assertEqual(1, TurningPoint.objects.count())
        self.assertEqual(TurningPointKind.FIRST_SEEN, TurningPoint.objects.first().kind)

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
        self.assertEqual(1, TurningPoint.objects.count())
        self.assertEqual(TurningPointKind.REGRESSED, TurningPoint.objects.first().kind)

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
        self.assertEqual(1, TurningPoint.objects.count())
        self.assertEqual(TurningPointKind.REGRESSED, TurningPoint.objects.first().kind)

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
        self.assertEqual(1, TurningPoint.objects.count())
        self.assertEqual(TurningPointKind.UNMUTED, TurningPoint.objects.first().kind)
        self.assertEqual(send_unmute_alert.delay.call_args[0][0], str(issue.id))
        self.assertEqual(
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
        self.assertEqual(1, TurningPoint.objects.count())
        self.assertEqual(TurningPointKind.UNMUTED, TurningPoint.objects.first().kind)
        self.assertEqual(send_unmute_alert.delay.call_args[0][0], str(issue.id))
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

            self.assertEqual(expected_called, send_new_issue_alert.delay.called)

            issue = Issue.objects.get(project=project)
            issue.is_resolved = True
            issue.save()

            # regression
            BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), project, request))

            self.assertEqual(expected_called, send_regression_alert.delay.called)

            # mute
            issue = Issue.objects.get(project=project)
            IssueStateManager.mute(issue, "[{\"period\": \"day\", \"nr_of_periods\": 1, \"volume\": 3}]")
            issue.save()

            # unmute via API
            BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), project, request))

            self.assertEqual(expected_called, send_unmute_alert.delay.called)

    def test_regression_on_first_event_for_release_when_declared_as_resolved_by_next(self):
        # a "regression" test about regressions: when the first event of a release is a regression, it should be
        # detected but this wasn't the case in the past.

        project = Project.objects.create(name="test")
        request = self.request_factory.post("/api/1/store/")

        # new event
        BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), project, request))

        issue = Issue.objects.get(project=project)
        issue.is_resolved = True
        issue.is_resolved_by_next_release = True
        issue.save()

        # regression, on new release
        event_data = create_event_data()
        event_data["release"] = "1.0"
        BaseIngestAPIView().digest_event(**_digest_params(event_data, project, request))

        issue = Issue.objects.get(project=project)
        self.assertEqual(False, issue.is_resolved)

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

        self.assertEqual(1, Issue.objects.count())
        self.assertEqual("1.0\n", Issue.objects.get().events_at)

    @tag("samples")
    def test_envelope_endpoint(self):
        # dirty copy/paste from the integration test, let's start with "something", we can always clean it later.
        project = Project.objects.create(name="test")

        sentry_auth_header = get_header_value(f"http://{ project.sentry_key }@hostisignored/{ project.id }")

        # first, we ingest many issues
        command = SendJsonCommand()
        command.stdout = io.StringIO()
        command.stderr = io.StringIO()

        SAMPLES_DIR = os.getenv("SAMPLES_DIR", "../event-samples")

        event_samples = glob(SAMPLES_DIR + "/*/*.json")
        known_broken = [SAMPLES_DIR + "/" + s.strip() for s in _readlines(SAMPLES_DIR + "/KNOWN-BROKEN")]

        if len(event_samples) == 0:
            raise Exception(f"No event samples found in {SAMPLES_DIR}; I insist on having some to test with.")

        for include_event_id in [True, False]:
            for filename in event_samples[:1]:  # one is enough here
                with open(filename) as f:
                    data = json.loads(f.read())

                data["event_id"] = uuid.uuid4().hex  # for good measure we reset this to avoid duplicates.

                if "timestamp" not in data:
                    # as per send_json command ("weirdly enough a large numer of sentry test data don't actually...")
                    data["timestamp"] = time.time()

                if not command.is_valid(data, filename):
                    if filename not in known_broken:
                        raise Exception("validatity check in %s: %s" % (filename, command.stderr.getvalue()))
                    command.stderr = io.StringIO()  # reset the error buffer; needed in the loop w/ known_broken

                event_id = data["event_id"]
                if not include_event_id:
                    del data["event_id"]

                data_bytes = json.dumps(data).encode("utf-8")
                data_bytes = (
                    b'{"event_id": "%s"}\n{"type": "event"}\n' % event_id.encode("utf-8") + data_bytes)

                response = self.client.post(
                    f"/api/{ project.id }/envelope/",
                    content_type="application/json",
                    headers={
                        "X-Sentry-Auth": sentry_auth_header,
                        "X-BugSink-DebugInfo": filename,
                    },
                    data=data_bytes,
                )
                self.assertEqual(
                    200, response.status_code, response.content if response.status_code != 302 else response.url)

    @tag("samples")
    def test_envelope_endpoint_reused_ids_different_exceptions(self):
        # dirty copy/paste from test_envelope_endpoint,
        project = Project.objects.create(name="test")

        sentry_auth_header = get_header_value(f"http://{ project.sentry_key }@hostisignored/{ project.id }")

        # first, we ingest many issues
        command = SendJsonCommand()
        command.stdout = io.StringIO()
        command.stderr = io.StringIO()

        SAMPLES_DIR = os.getenv("SAMPLES_DIR", "../event-samples")

        event_samples = glob(SAMPLES_DIR + "/sentry/mobile1-xen.json")  # this one has 'exception.values[0].type'
        known_broken = [SAMPLES_DIR + "/" + s.strip() for s in _readlines(SAMPLES_DIR + "/KNOWN-BROKEN")]

        if len(event_samples) == 0:
            raise Exception(f"No event samples found in {SAMPLES_DIR}; I insist on having some to test with.")

        for filename in event_samples[:1]:  # one is enough here
            with open(filename) as f:
                data = json.loads(f.read())
            data["event_id"] = uuid.uuid4().hex  # we set it once, before the loop.

            for type_ in ["Foo", "Bar"]:  # forces different groupers, leading to separate Issue objects
                data['exception']['values'][0]['type'] = type_

                if "timestamp" not in data:
                    # as per send_json command ("weirdly enough a large numer of sentry test data don't actually...")
                    data["timestamp"] = time.time()

                if not command.is_valid(data, filename):
                    if filename not in known_broken:
                        raise Exception("validatity check in %s: %s" % (filename, command.stderr.getvalue()))
                    command.stderr = io.StringIO()  # reset the error buffer; needed in the loop w/ known_broken

                event_id = data["event_id"]

                data_bytes = json.dumps(data).encode("utf-8")
                data_bytes = (
                    b'{"event_id": "%s"}\n{"type": "event"}\n' % event_id.encode("utf-8") + data_bytes)

                def check():
                    response = self.client.post(
                        f"/api/{ project.id }/envelope/",
                        content_type="application/json",
                        headers={
                            "X-Sentry-Auth": sentry_auth_header,
                            "X-BugSink-DebugInfo": filename,
                        },
                        data=data_bytes,
                    )
                    self.assertEqual(
                        200, response.status_code, response.content if response.status_code != 302 else response.url)

                if type_ == "Foo":
                    check()
                else:
                    with self.assertRaises(ViolatedExpectation):
                        check()

    @tag("samples")
    def test_envelope_endpoint_digest_non_immediate(self):
        with override_settings(DIGEST_IMMEDIATELY=False):
            self.test_envelope_endpoint()

    @tag("samples")
    def test_filestore(self):
        # quick & dirty way to test the filestore; in absence of a proper test for it, we just run a more-or-less
        # integration test with the FileEventStorage activated. This will at least show the absence of the most obvious
        # errors. We then run
        with tempfile.TemporaryDirectory() as tempdir:
            with override_event_storages({"local_flat_files": {
                        "STORAGE": "events.storage.FileEventStorage",
                        "OPTIONS": {
                            "basepath": tempdir,
                        },
                        "USE_FOR_WRITE": True,
                    },
                    }):
                self.test_envelope_endpoint()
                self.assertEqual(len(os.listdir(tempdir)), 2)  # test_envelope_endpoint creates 2 events

                project = Project.objects.get(name="test")
                project.retention_max_event_count = 1
                evict_for_max_events(project, timezone.now(), stored_event_count=2)

                self.assertEqual(len(os.listdir(tempdir)), 1)  # we set the max to 1, so one should remain

    @override_settings(MAX_EVENTS_PER_PROJECT_PER_5_MINUTES=0)
    @patch("ingest.views.check_for_thresholds")
    def test_count_project_periods_and_act_on_it_zero(self, patched_check_for_thresholds):
        # actually having a 0-quota would be nonsensical but let's at least not crash for that case

        patched_check_for_thresholds.side_effect = check_for_thresholds  # the patch is only there to count calls
        now = timezone.now()

        project = Project.objects.create(name="test")

        BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)

        # I don't care much for the exact handling of the nonsensical case, as long as "quota_exceeded" gets marked
        self.assertEqual(now + relativedelta(minutes=5), project.quota_exceeded_until)

    @override_settings(MAX_EVENTS_PER_PROJECT_PER_5_MINUTES=3)
    @patch("ingest.views.check_for_thresholds")
    def test_count_project_periods_and_act_on_it_simple_case(self, patched_check_for_thresholds):
        patched_check_for_thresholds.side_effect = check_for_thresholds  # the patch is only there to count calls
        now = timezone.now()

        project = Project.objects.create(name="test")

        # first call
        result = BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)

        self.assertEqual(True, result)
        self.assertEqual(1, project.digested_event_count)
        self.assertIsNone(project.quota_exceeded_until)
        self.assertEqual(1, patched_check_for_thresholds.call_count)

        create_event(project, timestamp=now)  # result was True, proceed accordingly

        # second call
        result = BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)

        self.assertEqual(True, result)
        self.assertEqual(2, project.digested_event_count)
        self.assertIsNone(project.quota_exceeded_until)
        self.assertEqual(1, patched_check_for_thresholds.call_count)  # no new call to the expensive check is done

        create_event(project, timestamp=now)  # result was True, proceed accordingly

        # third call (equals but does not exceed quota, so this event should still be accepted, but the door should be
        # closed right after it)
        result = BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)

        self.assertEqual(True, result)
        self.assertEqual(3, project.digested_event_count)
        self.assertEqual(now + relativedelta(minutes=5), project.quota_exceeded_until)
        self.assertEqual(2, patched_check_for_thresholds.call_count)  # the check was done right at the lower bound

        create_event(project, timestamp=now)  # result was True, proceed accordingly

        # fourth call
        result = BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)

        self.assertEqual(False, result)  # should be droped immediately
        self.assertEqual(3, project.digested_event_count)  # nothing is digested
        self.assertEqual(now + relativedelta(minutes=5), project.quota_exceeded_until)  # unchanged
        self.assertEqual(2, patched_check_for_thresholds.call_count)  # no expensive check (use quota_exceeded_until)

        # xth call (after a while)
        result = BaseIngestAPIView.count_project_periods_and_act_on_it(project, now + relativedelta(minutes=6))

        self.assertEqual(True, result)
        self.assertEqual(4, project.digested_event_count)
        self.assertIsNone(project.quota_exceeded_until)
        self.assertEqual(3, patched_check_for_thresholds.call_count)  # the check is done on "re-enter"

    @override_settings(MAX_EVENTS_PER_PROJECT_PER_5_MINUTES=3)
    @patch("ingest.views.check_for_thresholds")
    def test_count_project_periods_and_act_on_it_new_check_done_but_below_threshold(self, patched_check_for_thresholds):
        patched_check_for_thresholds.side_effect = check_for_thresholds  # the patch is only there to count calls
        now = timezone.now()

        project = Project.objects.create(name="test")

        # first and second call as in "simple_case" test
        BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)
        create_event(project, timestamp=now)  # result was True, proceed accordingly

        BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)
        create_event(project, timestamp=now)  # result was True, proceed accordingly

        # third call must trigger the check; if it happens outside of the 5-minute period the result should be OK though
        result = BaseIngestAPIView.count_project_periods_and_act_on_it(project, now + relativedelta(minutes=6))

        self.assertEqual(True, result)
        self.assertIsNone(project.quota_exceeded_until)
        self.assertEqual(2, patched_check_for_thresholds.call_count)  # the check was done right at the lower bound

    @override_settings(MAX_EVENTS_PER_PROJECT_PER_5_MINUTES=3)
    @patch("ingest.views.check_for_thresholds")
    def test_count_project_periods_and_act_on_it_immediate_overshoot(self, patched_check_for_thresholds):
        # a test that documents the current behavior for an edge case, rather than make a value-judgement about it. The
        # scenario is: what if an event comes into the digestion pipeline that is over budget (as opposed to being the
        # last in-budget item) while the project is still in accepting (quota_exceeded_until is None) state? Because we
        # digest serially, I don't see how this could happen except by changing the quota in flight or through a
        # programming error; in any case, the current test documents what happens in that case.
        patched_check_for_thresholds.side_effect = check_for_thresholds  # the patch is only there to count calls
        now = timezone.now()

        project = Project.objects.create(name="test")

        # first call (assertions implied, as in simple_case)
        result = BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)
        create_event(project, timestamp=now)  # result was True, proceed accordingly

        with override_settings(MAX_EVENTS_PER_PROJECT_PER_5_MINUTES=1):
            # the path described in this test only works if the next_quota_check are simultaneously reset
            project.next_quota_check = 0
            project.save()

            # second call, with down-tuned quota; the 2nd event would be immediately over-quota
            result = BaseIngestAPIView.count_project_periods_and_act_on_it(project, now)

            # despite being over-quota, we still accept it. This is the "document without value judgement" part of the
            # test.
            self.assertEqual(True, result)
            self.assertEqual(2, project.digested_event_count)

            # but at least this closes the door for the next event
            self.assertEqual(now + relativedelta(minutes=5), project.quota_exceeded_until)

    def test_ingest_updates_stored_event_counts(self):
        request = self.request_factory.post("/api/1/store/")

        BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), self.quiet_project, request))

        self.assertEqual(1, Issue.objects.count())
        self.assertEqual(1, Issue.objects.get().stored_event_count)
        self.assertEqual(1, Project.objects.get(id=self.quiet_project.id).stored_event_count)

        BaseIngestAPIView().digest_event(**_digest_params(create_event_data(), self.quiet_project, request))
        self.assertEqual(2, Issue.objects.get().stored_event_count)
        self.assertEqual(2, Project.objects.get(id=self.quiet_project.id).stored_event_count)


class TestParser(RegularTestCase):

    def test_readuntil_newline_everything_in_initial_chunk(self):
        input_stream = io.BytesIO(b"line 2\nline 3\n")
        initial_chunk = b"line 0\nline 1\n"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEqual(b"line 0", output_stream.getvalue())
        self.assertEqual(b"line 1\n", remainder)
        self.assertEqual(b"line 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_with_initial_chunk(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEqual(b"line 0", output_stream.getvalue())
        self.assertEqual(b"li", remainder)
        self.assertEqual(b"ne 1\nline 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_no_initial_chunk(self):
        input_stream = io.BytesIO(b"line 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b""
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEqual(b"line 0", output_stream.getvalue())
        self.assertEqual(b"li", remainder)
        self.assertEqual(b"ne 1\nline 2\nline 3\n", input_stream.read())

    def test_readuntil_newline_until_eof(self):
        input_stream = io.BytesIO(b"line 0")
        initial_chunk = b""
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 3)

        self.assertTrue(at_eof)
        self.assertEqual(b"line 0", output_stream.getvalue())
        self.assertEqual(b"", remainder)
        self.assertEqual(b"", input_stream.read())

    def test_readuntil_newline_bigger_chunk(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, NewlineFinder(), output_stream, 1024)

        self.assertFalse(at_eof)
        self.assertEqual(b"line 0", output_stream.getvalue())
        self.assertEqual(b"line 1\nline 2\nline 3\n", remainder)
        self.assertEqual(b"", input_stream.read())

    def test_readuntil_length(self):
        input_stream = io.BytesIO(b"e 0\nline 1\nline 2\nline 3\n")
        initial_chunk = b"lin"
        input_stream.seek(0)

        output_stream = io.BytesIO()
        remainder, at_eof = readuntil(input_stream, initial_chunk, LengthFinder(10, "eof not ok"), output_stream, 3)

        self.assertFalse(at_eof)
        self.assertEqual(b"line 0\nlin", output_stream.getvalue())
        self.assertEqual(b"e ", remainder)
        self.assertEqual(b"1\nline 2\nline 3\n", input_stream.read())

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
        self.assertEqual(
            {"event_id": "9ec79c33ec9942ab8353589fcb2e04dc",
             "dsn": "https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"},
            envelope_headers)

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEqual(
            {"type": "attachment", "length": 10, "content_type": "text/plain", "filename": "hello.txt"},
            header)  # we check item-header parsing once, should be enough.
        self.assertEqual(b"\xef\xbb\xbfHello\r\n", item)

        header, item = next(items)
        self.assertEqual(b'{"message":"hello world","level":"error"}', item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_envelope_with_2_items_last_newline_omitted(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\n{"type":"attachment","length":10,"content_type":"text/plain","filename":"hello.txt"}\n\xef\xbb\xbfHello\r\n\n{"type":"event","length":41,"content_type":"application/json","filename":"application.log"}\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEqual(b"\xef\xbb\xbfHello\r\n", item)

        header, item = next(items)
        self.assertEqual(b'{"message":"hello world","level":"error"}', item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_envelope_with_2_empty_attachments(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc"}\n{"type":"attachment","length":0}\n\n{"type":"attachment","length":0}\n\n"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEqual(b"", item)

        header, item = next(items)
        self.assertEqual(b"", item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_envelope_with_2_empty_attachments_last_newline_omitted(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc"}\n{"type":"attachment","length":0}\n\n{"type":"attachment","length":0}\n"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEqual(b"", item)

        header, item = next(items)
        self.assertEqual(b"", item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_item_with_implicit_length_terminated_by_newline(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc"}\n{"type":"attachment"}\nhelloworld\n"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEqual(b"helloworld", item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_item_with_implicit_length_last_newline_omitted_terminated_by_eof(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc"}\n{"type":"attachment"}\nhelloworld"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEqual(b"helloworld", item)

        with self.assertRaises(StopIteration):
            next(items)

    def test_envelope_without_headers_implicit_length_last_newline_omitted_terminated_by_eof(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{}\n{"type":"session"}\n{"started": "2020-02-07T14:16:00Z","attrs":{"release":"sentry-test@1.0.0"}}"""))  # noqa

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEqual(b'{"started": "2020-02-07T14:16:00Z","attrs":{"release":"sentry-test@1.0.0"}}', item)

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
        self.assertEqual("EOF while reading item with explicitly specified length", str(e.exception))

    def test_too_much_content_aka_length_too_short(self):
        # based on test_envelope_with_2_items_last_newline_omitted, but with length "41" replaced by "40"

        # > Length-prefixed payloads must terminate with \n or EOF. The newline is not considered part of the payload.
        # > Any other character, including whitespace, means the Envelope is malformed.
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\n{"type":"event","length":40,"content_type":"application/json","filename":"application.log"}\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        with self.assertRaises(ParseError) as e:
            header, item = next(items)
        self.assertEqual("Item with explicit length not terminated by newline/EOF", str(e.exception))

    def test_non_json_header(self):
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{"event_id":"9ec79c33ec9942ab8353589fcb2e04dc","dsn":"https://e12d836b15bb49d7bbf99e64295d995b:@sentry.io/42"}\nTHIS IS NOT JSON\n{"message":"hello world","level":"error"}"""))  # noqa

        items = parser.get_items_directly()

        with self.assertRaises(ParseError) as e:
            header, item = next(items)
        self.assertEqual("Header not JSON", str(e.exception))

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
        self.assertEqual("EOF when reading headers; what is this a header for then?", str(e.exception))

    def test_item_headers_but_no_item(self):
        # another edge case that we don't care about much (no data)
        # as per test_item_with_implicit_length_last_newline_omitted_terminated_by_eof, "implicit lenght and last
        # newline omitted" is a valid combination. We make explicit that this is also the case for 0-length item
        parser = StreamingEnvelopeParser(io.BytesIO(b"""{}\n{}\n"""))

        items = parser.get_items_directly()

        header, item = next(items)
        self.assertEqual(b"", item)

        with self.assertRaises(StopIteration):
            header, item = next(items)
