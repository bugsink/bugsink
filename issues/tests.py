from unittest import TestCase
from unittest.mock import patch
from django.test import TestCase as DjangoTestCase
from datetime import datetime, timezone

from projects.models import Project
from releases.models import create_release_if_needed
from bugsink.registry import reset_pc_registry, get_pc_registry
from bugsink.period_counter import TL_DAY

from .models import Issue, IssueStateManager
from .regressions import is_regression, is_regression_2, issue_is_regression


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class RegressionUtilTestCase(TestCase):
    # This tests the concept of "what is a regression?", it _does not_ test for regressions in our code :-)
    # this particular testcase tests straight on the utility `is_regression` (i.e. not all issue-handling code)

    def setUp(self):
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

        self.assertEquals(False, is_regression(self.releases, fixed_at, events_at, current_event_at="a"))
        self.assertEquals(False, is_regression(self.releases, fixed_at, events_at, current_event_at="b"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="c"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="d"))
        self.assertEquals(False, is_regression(self.releases, fixed_at, events_at, current_event_at="e"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="f"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="g"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, events_at, current_event_at="h"))

        self.assertEquals((False, True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="a"))
        self.assertEquals((False, True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="b"))
        # the interesting bit from this block: a regression, but fixed already (for a later version)
        self.assertEquals((True,  True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="c"))
        self.assertEquals((True,  True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="d"))
        self.assertEquals((False, True), is_regression_2(self.releases, fixed_at, events_at, current_event_at="e"))
        self.assertEquals((True,  False), is_regression_2(self.releases, fixed_at, events_at, current_event_at="f"))
        self.assertEquals((True,  False), is_regression_2(self.releases, fixed_at, events_at, current_event_at="g"))
        self.assertEquals((True,  False), is_regression_2(self.releases, fixed_at, events_at, current_event_at="h"))

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

        # new issue is not a regression
        issue = Issue.objects.create(project=project)
        self.assertFalse(issue_is_regression(fresh(issue), "anything"))

        # resolve the issue, a reoccurrence is a regression
        IssueStateManager.resolve(issue)
        issue.save()
        self.assertTrue(issue_is_regression(fresh(issue), "anything"))

        # reopen the issue (as is done when a real regression is seen; or as would be done manually); nothing is a
        # regression once the issue is open
        IssueStateManager.reopen(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "anything"))

    def test_issue_is_regression_with_releases_resolve_by_latest(self):
        project = Project.objects.create()

        create_release_if_needed(project, "1.0.0")
        create_release_if_needed(project, "2.0.0")

        # new issue is not a regression
        issue = Issue.objects.create(project=project)
        self.assertFalse(issue_is_regression(fresh(issue), "anything"))

        # resolve the by latest, reoccurrences of older releases are not regressions but occurrences by latest are
        IssueStateManager.resolve_by_latest(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertTrue(issue_is_regression(fresh(issue), "2.0.0"))

        # a new release happens, and the issue is seen there: also a regression
        create_release_if_needed(project, "3.0.0")
        self.assertTrue(issue_is_regression(fresh(issue), "3.0.0"))

        # reopen the issue (as is done when a real regression is seen; or as would be done manually); nothing is a
        # regression once the issue is open
        IssueStateManager.reopen(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertFalse(issue_is_regression(fresh(issue), "2.0.0"))

    def test_issue_is_regression_with_releases_resolve_by_next(self):
        project = Project.objects.create()

        create_release_if_needed(project, "1.0.0")
        create_release_if_needed(project, "2.0.0")

        # new issue is not a regression
        issue = Issue.objects.create(project=project)
        self.assertFalse(issue_is_regression(fresh(issue), "anything"))

        # resolve the by next, reoccurrences of any existing releases are not regressions
        IssueStateManager.resolve_by_next(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertFalse(issue_is_regression(fresh(issue), "2.0.0"))

        # a new release appears (as part of a new event); this is a regression
        create_release_if_needed(project, "3.0.0")
        self.assertTrue(issue_is_regression(fresh(issue), "3.0.0"))

        # first-seen at any later release: regression
        create_release_if_needed(project, "4.0.0")
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


class UnmuteTestCase(TestCase):

    def setUp(self):
        """
        (TODO The below is not implemented yet; we may need it at some point)

        To avoid unintentional modifications to the pc_registry in tests without a recent reset, consider the following

        1. In each setup method, explicitly set a testing flag to indicate that it is safe to interact
           with the pc_registry. For example, include the line:
              `set_testing_flag(True)` (as well as resetting the pc_registry)

        2. In each tearDown method, reset the testing flag to indicate that further modifications
           to the pc_registry should be avoided. For example, include the line:
              `set_testing_flag(False)`

        This approach helps prevent accidental influences of one test on another via the pc_registry.
        """
        reset_pc_registry()

    def tearDown(self):
        reset_pc_registry()

    @patch("issues.models.send_unmute_alert")
    def test_unmute_simple_case(self, send_unmute_alert):
        project = Project.objects.create()

        issue = Issue.objects.create(
            project=project,
            unmute_on_volume_based_conditions='[{"period": "day", "nr_of_periods": 1, "volume": 1}]',
            is_muted=True,
        )

        # because we create our objects before getting the lazy registry, event-listeners will be correctly set by
        # registry.load_from_scratch()
        registry = get_pc_registry()

        registry.by_issue[issue.id].inc(datetime.now(timezone.utc))

        self.assertFalse(Issue.objects.get(id=issue.id).is_muted)
        self.assertEquals("[]", Issue.objects.get(id=issue.id).unmute_on_volume_based_conditions)
        self.assertEquals({}, registry.by_issue[issue.id].event_listeners[TL_DAY])

        self.assertEquals(1, send_unmute_alert.delay.call_count)

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
        )

        # because we create our objects before getting the lazy registry, event-listeners will be correctly set by
        # registry.load_from_scratch()
        registry = get_pc_registry()

        registry.by_issue[issue.id].inc(datetime.now(timezone.utc))

        self.assertFalse(Issue.objects.get(id=issue.id).is_muted)
        self.assertEquals("[]", Issue.objects.get(id=issue.id).unmute_on_volume_based_conditions)
        self.assertEquals({}, registry.by_issue[issue.id].event_listeners[TL_DAY])

        self.assertEquals(1, send_unmute_alert.delay.call_count)
