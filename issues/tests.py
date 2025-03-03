import requests
import os
import inspect
import uuid
import json
from io import StringIO
from glob import glob
from unittest import TestCase as RegularTestCase
from unittest.mock import patch
from datetime import datetime, timezone

from django.test import TestCase as DjangoTestCase
from django.contrib.auth import get_user_model
from django.test import tag
from django.conf import settings

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project, ProjectMembership
from releases.models import create_release_if_needed
from events.factories import create_event
from bsmain.management.commands.send_json import Command as SendJsonCommand
from compat.dsn import get_header_value
from events.models import Event
from ingest.views import BaseIngestAPIView
from issues.factories import get_or_create_issue

from .models import Issue, IssueStateManager
from .regressions import is_regression, is_regression_2, issue_is_regression
from .factories import denormalized_issue_fields
from .utils import get_issue_grouper_for_data

User = get_user_model()


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _readlines(filename):
    with open(filename) as f:
        return f.readlines()


class RegressionUtilTestCase(RegularTestCase):
    # This tests the concept of "what is a regression?", it _does not_ test for regressions in our code :-)
    # this particular testcase tests straight on the utility `is_regression` (i.e. not all issue-handling code)

    def setUp(self):
        super().setUp()
        self.releases = ["a", "b", "c", "d", "e", "f", "g", "h"]

    def test_not_marked_as_fixed(self):
        # by definition: not marked as fixed means we cannot regress.
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=[],
            events_at=[],
            current_event_at="h"))

        # same but with observed issues
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=[],
            events_at=["b", "c", "f"],
            current_event_at="h"))

    def test_first_regression(self):
        # breakage in the very release marked as the fix
        self.assertTrue(is_regression(
            self.releases,
            fixed_at=["b"],
            events_at=["a"],
            current_event_at="b"))

        # breakage in a later release
        self.assertTrue(is_regression(
            self.releases,
            fixed_at=["b"],
            events_at=["a"],
            current_event_at="c"))

        # events_at empty list (not expected to happen in real code, because how would you mark as fixed?)
        # just proceed as above.
        self.assertTrue(is_regression(
            self.releases,
            fixed_at=["b"],
            events_at=[],
            current_event_at="b"))

    def test_non_regressions(self):
        # breakage before the fix
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=["b"],
            events_at=["a"],
            current_event_at="a"))

        # breakage before the fix, but in a release the error had not been seen before.
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=["c"],
            events_at=["a"],
            current_event_at="b"))

    def test_observations_override_marked_resolutions(self):
        # if an issue has been marked as resolved but has also (presumably later on) been seen in reality to not have
        # been resolved, it is not resolved by that release. Hence, re-occurrence is not a (new) regression.
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=["c"],
            events_at=["c"],
            current_event_at="c"))

    def test_longer_patterns(self):
        # Our model of regressions allows one to express brokennes over (linear) time, which is what this test proves.
        # In particular: we keep track of more than one "fixed at" release, which allows us to warn about breakage
        # _before_ the latest fix but after (or at the moment of) an earlier fix.
        #
        #        breakage                fix                breakage      fix
        #           a          b          c         d           e          f          g          h
        #                                 ^         ^
        #                           our model allows us to warn about these points
        #
        # (We take on some complexity because of it, but avoiding False negatives is the number 1 priority of this
        # software so I believe it's justified)
        events_at = ["a", "e"]
        fixed_at = ["c", "f"]

        self.assertEqual(False, is_regression(self.releases, fixed_at, events_at, current_event_at="a"))
        self.assertEqual(False, is_regression(self.releases, fixed_at, events_at, current_event_at="b"))
        self.assertEqual(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="c"))
        self.assertEqual(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="d"))
        self.assertEqual(False, is_regression(self.releases, fixed_at, events_at, current_event_at="e"))
        self.assertEqual(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="f"))
        self.assertEqual(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="g"))
        self.assertEqual(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="h"))

        self.assertEqual((False, True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="a"))
        self.assertEqual((False, True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="b"))
        # the interesting bit from this block: a regression, but fixed already (for a later version)
        self.assertEqual((True,  True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="c"))
        self.assertEqual((True,  True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="d"))
        self.assertEqual((False, True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="e"))
        self.assertEqual((True,  False), is_regression_2(self.releases, fixed_at, events_at, current_event_at="f"))
        self.assertEqual((True,  False), is_regression_2(self.releases, fixed_at, events_at, current_event_at="g"))
        self.assertEqual((True,  False), is_regression_2(self.releases, fixed_at, events_at, current_event_at="h"))

    def test_documented_thoughts_about_minor_and_patch_releases(self):
        # this test-case documents the limitation of our approach in the following combination of circumstances:
        #
        # * (correctly ordered) semantic verion releases are used
        # * release branches are maintained (and live, i.e. producing events)
        # * an error occurs on an older minor/patch version of a more recent major branch
        #
        # In the example below: an error is detected on both 3.1.1 and 4.0.1 and fixed in patch releases for those
        # branches. In a non-linear model one would expect 3.1.2 and up and 4.0.2 and up to be fixed (but not 4.0.0).
        # Because we flatten the releases in a single timeline, we cannot be so subtle (we basically see 4.0.0 as a
        # follow-up of 3.1.2)
        #
        # In practice, this is probably rarely a problem, because for the regression to be falsely detected it should
        # also [1] never have occured on the older (4.0.0) version and [2] the old version should still linger somewhere
        # (less likely if you're pushing out a fix).
        #
        # For now the trade-off between extra complexity and full correctness (avoiding false positives) is clearly in
        # favor of simplicity. If this ever turns out to be a regularly occurring situation, explicit marking-as-broken
        # might be another way forward (rather than introducing a non-total order on releases).

        releases = ["3.1.0", "3.1.1", "3.1.2", "4.0.0", "4.0.1", "4.0.2"]
        events_at = ["3.1.1", "4.0.1"]
        fixed_at = ["3.1.2", "4.0.2"]

        # In an ideal world: assertFalse
        self.assertTrue(is_regression(releases, fixed_at, events_at, current_event_at="4.0.0"))

        # Note that if we abandon sort-by-version, and instead order by time-of-creation, the unideal behavior goes away
        # automatically...
        releases = ["3.1.0", "3.1.1", "4.0.0", "4.0.1", "3.1.2", "4.0.2"]
        self.assertFalse(is_regression(releases, fixed_at, events_at, current_event_at="4.0.0"))

        # ... however, that introduces its own problems, such as not being able to mark the _lack_ of fixing in the
        # most recent major branch. (in the below, there is no fix on the 4.x branch reported, but a regression is
        # detected when 4.0.2 has the same problem it had in 4.0.1), i.e. the below should say 'assertFalse'
        self.assertTrue(is_regression(releases, ["3.1.2"], events_at, current_event_at="4.0.2"))


class RegressionIssueTestCase(DjangoTestCase):
    # this particular testcase is more of an integration test: it tests the handling of issue objects.

    def test_issue_is_regression_no_releases(self):
        project = Project.objects.create()
        create_release_if_needed(fresh(project), "", create_event(project))

        # new issue is not a regression
        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        self.assertFalse(issue_is_regression(fresh(issue), ""))

        # resolve the issue, a reoccurrence is a regression
        IssueStateManager.resolve(issue)
        issue.save()
        self.assertTrue(issue_is_regression(fresh(issue), ""))

        # reopen the issue (as is done when a real regression is seen; or as would be done manually); nothing is a
        # regression once the issue is open
        IssueStateManager.reopen(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), ""))

    def test_issue_had_no_releases_but_now_does(self):
        project = Project.objects.create()
        create_release_if_needed(fresh(project), "", create_event(project))

        # new issue is not a regression
        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        self.assertFalse(issue_is_regression(fresh(issue), ""))

        # resolve the issue, a reoccurrence is a regression
        IssueStateManager.resolve(issue)
        issue.save()

        # a new release happens
        create_release_if_needed(fresh(project), "1.0.0", create_event(project))

        self.assertTrue(issue_is_regression(fresh(issue), "1.0.0"))

    def test_issue_is_regression_with_releases_resolve_by_latest(self):
        project = Project.objects.create()

        create_release_if_needed(fresh(project), "1.0.0", create_event(project))
        create_release_if_needed(fresh(project), "2.0.0", create_event(project))

        # new issue is not a regression
        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        self.assertFalse(issue_is_regression(fresh(issue), "anything"))

        # resolve the by latest, reoccurrences of older releases are not regressions but occurrences by latest are
        IssueStateManager.resolve_by_latest(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertTrue(issue_is_regression(fresh(issue), "2.0.0"))

        # a new release happens, and the issue is seen there: also a regression
        create_release_if_needed(fresh(project), "3.0.0", create_event(project))
        self.assertTrue(issue_is_regression(fresh(issue), "3.0.0"))

        # reopen the issue (as is done when a real regression is seen; or as would be done manually); nothing is a
        # regression once the issue is open
        IssueStateManager.reopen(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertFalse(issue_is_regression(fresh(issue), "2.0.0"))

    def test_issue_is_regression_with_releases_resolve_by_next(self):
        project = Project.objects.create()

        create_release_if_needed(fresh(project), "1.0.0", create_event(project))
        create_release_if_needed(fresh(project), "2.0.0", create_event(project))

        # new issue is not a regression
        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        self.assertFalse(issue_is_regression(fresh(issue), "anything"))

        # resolve the by next, reoccurrences of any existing releases are not regressions
        IssueStateManager.resolve_by_next(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertFalse(issue_is_regression(fresh(issue), "2.0.0"))

        # a new release appears (as part of a new event); this is a regression
        create_release_if_needed(fresh(project), "3.0.0", create_event(project))
        self.assertTrue(issue_is_regression(fresh(issue), "3.0.0"))

        # first-seen at any later release: regression
        create_release_if_needed(fresh(project), "4.0.0", create_event(project))
        self.assertTrue(issue_is_regression(fresh(issue), "4.0.0"))


"""
Some thoughts on re-opening, that I have to put 'somewhere'; might as well put them here in the tests where I first
thought of them... The direct cause for these thoughts was that I found it very hard to reason about the following
question: "what does re-opening an issue mean for the `fixed_at` points?"

First: re-opening an issue (from the UI) is kinda funny in the first place. What are you saying by doing that anyway?
You're saying "this is an issue that continues to exist, despite me/someone at some point saying that it was resolved".
You're doing this with "pure brainpower", i.e. by thinking it through rather than waiting for an issue to reoccur
naturally.

Why would you ever want to do this? My main guess is: to undo a click on resolve that you just did. If that's so, we
might implement re-open more closely as such an undo (and the anwer to the first question would also follow from it,
i.e. it would be "the last-added `fixed_at` point should be removed"

The main consequences of re-opening are: you won't be bothered (alerts) about a regression that you just understood to
still exist. And: if you go looking for unresolved issues, you'll find this one.

Having said all of that, I might do something radical and _not implement reopen in the UI at all!_ Let's see if I run
into the lack of it existing.

... having said that, it's not _that bad_, and I think I could answer the original question, if pressed (allowing us to
reintroduce the Reopen button in the UI). I would simply say: let's not bother doing a proper administration of
`fixed_at` points when the issue is manually reopened. Manually reopening as such allows us to avoid an alert that we
don't need, and get our administration of not-yet-resolved issues in order. The only scenario where this goes wrong is
something along these lines:

at some point ("a") which does not have seen breakage we mark as resolved. we then reopen. "a" remains marked as
resolved, because we're in the "let's not bother" scenario. Then, we get a later point where we first see the issue in
the wild ("b") and resolve it ("c"). Then, if we were to see it again in "a", as per the test_longer_patterns, this
would be seen as a regression when in reality it was never solved in "a", and its marking-as-such should probably have
seen as an undo rather than anything else.
"""


class MuteUnmuteTestCase(TransactionTestCase):
    """
    Somewhat of an integration test. The unit-under-test here is the whole of
    * BaseIngestAPIView.count_issue_periods_and_act_on_it
    * threshold-counting
    * IssueStateManager.unmute
    """

    def test_mute_no_vbc_for_unmute(self):
        project = Project.objects.create()

        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        IssueStateManager.mute(issue, "[]")
        issue.save()

    def test_mute_simple_case(self):
        project = Project.objects.create()

        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        IssueStateManager.mute(issue, "[{\"period\": \"day\", \"nr_of_periods\": 1, \"volume\": 1}]")
        issue.save()

    @patch("issues.models.send_unmute_alert")
    def test_unmute_alerts_should_not_be_sent_when_users_click_unmute(self, send_unmute_alert):
        project = Project.objects.create()

        issue = Issue.objects.create(
            project=project,
            unmute_on_volume_based_conditions='[]',
            is_muted=True,
            **denormalized_issue_fields(),
        )

        IssueStateManager.unmute(issue)
        issue.save()

        self.assertFalse(Issue.objects.get(id=issue.id).is_muted)
        self.assertEqual(0, send_unmute_alert.delay.call_count)

    @patch("issues.models.send_unmute_alert")
    def test_unmute_simple_case(self, send_unmute_alert):
        project = Project.objects.create()

        issue = Issue.objects.create(
            project=project,
            unmute_on_volume_based_conditions='[{"period": "day", "nr_of_periods": 1, "volume": 1}]',
            is_muted=True,
            **denormalized_issue_fields(),
        )

        event = create_event(project, issue)
        BaseIngestAPIView.count_issue_periods_and_act_on_it(issue, event, datetime.now(timezone.utc))
        issue.save()

        self.assertFalse(Issue.objects.get(id=issue.id).is_muted)
        self.assertEqual("[]", Issue.objects.get(id=issue.id).unmute_on_volume_based_conditions)

        self.assertEqual(1, send_unmute_alert.delay.call_count)

    @patch("issues.models.send_unmute_alert")
    def test_unmute_two_simultaneously_should_lead_to_one_alert(self, send_unmute_alert):
        project = Project.objects.create()

        issue = Issue.objects.create(
            project=project,
            unmute_on_volume_based_conditions='''[
    {"period": "day", "nr_of_periods": 1, "volume": 1},
    {"period": "month", "nr_of_periods": 1, "volume": 1}
]''',
            is_muted=True,
            **denormalized_issue_fields(),
        )

        event = create_event(project, issue)
        BaseIngestAPIView.count_issue_periods_and_act_on_it(issue, event, datetime.now(timezone.utc))
        issue.save()

        self.assertFalse(Issue.objects.get(id=issue.id).is_muted)
        self.assertEqual("[]", Issue.objects.get(id=issue.id).unmute_on_volume_based_conditions)

        self.assertEqual(1, send_unmute_alert.delay.call_count)


class ViewTests(TransactionTestCase):
    # we start with minimal "does this show something and not fully crash" tests and will expand from there.

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', password='test')
        self.project = Project.objects.create()
        ProjectMembership.objects.create(project=self.project, user=self.user)
        self.issue, _ = get_or_create_issue(self.project)
        self.event = create_event(self.project, self.issue)
        self.client.force_login(self.user)

    def test_issue_list_view(self):
        response = self.client.get(f"/issues/{self.project.id}/")
        self.assertContains(response, self.issue.title())

    def test_issue_stacktrace(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{self.event.id}/")
        self.assertContains(response, self.issue.title())

    def test_issue_details(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{self.event.id}/details/")
        self.assertContains(response, self.issue.title())

    def test_issue_tags(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/tags/")
        self.assertContains(response, self.issue.title())

    def test_issue_history(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/history/")
        self.assertContains(response, self.issue.title())

    def test_issue_event_list(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/events/")
        self.assertContains(response, self.issue.title())


@tag("samples")
@tag("integration")
class IntegrationTest(TransactionTestCase):

    def setUp(self):
        super().setUp()
        self.verbosity = self.get_verbosity()

    def get_verbosity(self):
        # https://stackoverflow.com/a/27457315/339144
        for s in reversed(inspect.stack()):
            options = s[0].f_locals.get('options')
            if isinstance(options, dict):
                return int(options['verbosity'])
        return 1

    def test_many_issues_ingest_and_show(self):
        user = User.objects.create_user(username='test', password='test')
        project = Project.objects.create(name="test")
        ProjectMembership.objects.create(project=project, user=user)
        self.client.force_login(user)

        sentry_auth_header = get_header_value(f"http://{ project.sentry_key }@hostisignored/{ project.id }")

        # first, we ingest many issues
        command = SendJsonCommand()
        command.stdout = StringIO()
        command.stderr = StringIO()

        # the following may be used for faster debugging of individual failures:
        # for filename in ["...failing filename here..."]:

        # event-samples-private contains events that I have dumped from my local development environment, but which I
        # have not bothered cleaning up, and can thus not be publically shared.
        SAMPLES_DIR = os.getenv("SAMPLES_DIR", "../event-samples")

        event_samples = glob(SAMPLES_DIR + "/*/*.json")
        event_samples_private = glob("../event-samples-private/*.json")
        known_broken = [SAMPLES_DIR + "/" + s.strip() for s in _readlines(SAMPLES_DIR + "/KNOWN-BROKEN")]

        if len(event_samples) == 0:
            raise Exception(f"No event samples found in {SAMPLES_DIR}; I insist on having some to test with.")

        if self.verbosity > 1:
            print(f"Found {len(event_samples)} event samples and {len(event_samples_private)} private event samples")

        try:
            github_result = requests.get(
                "https://raw.githubusercontent.com/getsentry/sentry-data-schemas/main/relay/event.schema.json")
            github_result.raise_for_status()

            with open(settings.BASE_DIR / "api/event.schema.json", "r") as f:
                my_contents = f.read()

            self.assertEqual(my_contents, github_result.content.decode("utf-8"), "event.schema.json is not up-to-date")
        except requests.RequestException:
            # getting the latest schema "once in a while" is nice so that we can be sure we're not falling behind;
            # but we don't want that to introduce a point-of-failure in our tests. So print-and-continue.
            print("Could not fetch the latest event schema from GitHub; I will not fail the tests for this")

        for filename in event_samples + event_samples_private:
            with open(filename) as f:
                data = json.loads(f.read())

            # we do this because our samples do not have unique event_ids; additionally this sets the event_id if it's
            # not set in the sample (it sometimes isn't); (the fact that we can deal with that case is separately
            # tested)
            data["event_id"] = uuid.uuid4().hex

            if not command.is_valid(data, filename):
                if filename not in known_broken:
                    raise Exception("validatity check in %s: %s" % (filename, command.stderr.getvalue()))
                command.stderr = StringIO()  # reset the error buffer; needed in the loop w/ known_broken

            response = self.client.post(
                f"/api/{ project.id }/store/",
                json.dumps(data),
                content_type="application/json",
                headers={
                    "X-Sentry-Auth": sentry_auth_header,
                    "X-BugSink-DebugInfo": filename,
                },
            )
            self.assertEqual(
                200, response.status_code, "Error in %s: %s" % (
                    filename, response.content if response.status_code != 302 else response.url))

        for event in Event.objects.all():
            urls = [
                f'/issues/issue/{ event.issue.id }/event/{ event.id }/',
                f'/issues/issue/{ event.issue.id }/event/{ event.id }/details/',
                f'/issues/issue/{ event.issue.id }/event/{ event.id }/breadcrumbs/',
                f'/issues/issue/{ event.issue.id }/history/',
                f'/issues/issue/{ event.issue.id }/tags/',
                f'/issues/issue/{ event.issue.id }/grouping/',
                f'/issues/issue/{ event.issue.id }/events/',
            ]

            for url in urls:
                try:
                    # we just check for a 200; this at least makes sure we have no failing template rendering
                    response = self.client.get(url)
                    self.assertEqual(
                        200, response.status_code, response.content if response.status_code != 302 else response.url)

                    # The following code may be used to save the rendered pages for later inspection, e.g. using Nu HTML
                    # with open("/tmp/pages/" + url.replace("/", "_") + ".html", "w") as f:
                    #     f.write(response.content.decode("utf-8"))

                except Exception as e:
                    # we want to know _which_ event failed, hence the raise-from-e here
                    raise AssertionError("Error rendering event %s" % event.debug_info) from e


class GroupingUtilsTestCase(DjangoTestCase):

    def test_empty_data(self):
        self.assertEqual("Log Message: <no log message> ⋄ <no transaction>", get_issue_grouper_for_data({}))

    def test_logentry_message_takes_precedence(self):
        self.assertEqual("Log Message: msg: ? ⋄ <no transaction>", get_issue_grouper_for_data({"logentry": {
            "message": "msg: ?",
            "formatted": "msg: foobar",
        }}))

    def test_logentry_with_formatted_only(self):
        self.assertEqual("Log Message: msg: foobar ⋄ <no transaction>", get_issue_grouper_for_data({"logentry": {
            "formatted": "msg: foobar",
        }}))

    def test_logentry_with_transaction(self):
        self.assertEqual("Log Message: msg ⋄ transaction", get_issue_grouper_for_data({
            "logentry": {
                "message": "msg",
            },
            "transaction": "transaction",
        }))

    def test_exception_empty_trace(self):
        self.assertEqual("<unknown> ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [],
        }}))

    def test_exception_trace_no_data(self):
        self.assertEqual("<unknown> ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{}],
        }}))

    def test_exception_value_only(self):
        self.assertEqual("Error: exception message ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{"value": "exception message"}],
        }}))

    def test_exception_type_only(self):
        self.assertEqual("KeyError ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{"type": "KeyError"}],
        }}))

    def test_exception_type_value(self):
        self.assertEqual("KeyError: exception message ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{"type": "KeyError", "value": "exception message"}],
        }}))

    def test_exception_multiple_frames(self):
        self.assertEqual("KeyError: exception message ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{}, {}, {}, {"type": "KeyError", "value": "exception message"}],
        }}))

    def test_exception_transaction(self):
        self.assertEqual("KeyError ⋄ transaction", get_issue_grouper_for_data({
            "transaction": "transaction",
            "exception": {
                "values": [{"type": "KeyError"}],
            }
        }))

    def test_exception_function_is_ignored_unless_specifically_synthetic(self):
        # I make no value-judgement here on whether this is something we want to replicate in the future; as it stands
        # this test just documents the somewhat surprising behavior that we inherited from GlitchTip/Sentry.
        self.assertEqual("Error ⋄ <no transaction>", get_issue_grouper_for_data({
            "exception": {
                "values": [{
                    "stacktrace": {
                        "frames": [{"function": "foo"}],
                    },
                }],
            },
        }))

    def test_synthetic_exception_only(self):
        self.assertEqual("<unknown> ⋄ <no transaction>", get_issue_grouper_for_data({
            "exception": {
                "values": [{
                    "mechanism": {"synthetic": True},
                }],
            },
        }))

    def test_synthetic_exception_ignores_value(self):
        self.assertEqual("<unknown> ⋄ <no transaction>", get_issue_grouper_for_data({
            "exception": {
                "values": [{
                    "mechanism": {"synthetic": True},
                    "value": "the ignored value",
                }],
            },
        }))

    def test_exception_uses_function_when_top_level_exception_is_synthetic(self):
        self.assertEqual("foo ⋄ <no transaction>", get_issue_grouper_for_data({
            "exception": {
                "values": [{
                    "mechanism": {"synthetic": True},
                    "stacktrace": {
                        "frames": [{"function": "foo"}],
                    },
                }],
            },
        }))

    def test_exception_with_non_string_value(self):
        # In the GlitchTip code there is a mention of value sometimes containing a non-string value. Whether this
        # happens in practice is unknown to me, but let's build something that can handle it.
        self.assertEqual("KeyError: 123 ⋄ <no transaction>", get_issue_grouper_for_data({"exception": {
            "values": [{"type": "KeyError", "value": 123}],
        }}))

    def test_simple_fingerprint(self):
        self.assertEqual("fixed string", get_issue_grouper_for_data({"fingerprint": ["fixed string"]}))

    def test_fingerprint_with_default(self):
        self.assertEqual("Log Message: <no log message> ⋄ <no transaction> ⋄ fixed string",
                         get_issue_grouper_for_data({"fingerprint": ["{{ default }}", "fixed string"]}))
