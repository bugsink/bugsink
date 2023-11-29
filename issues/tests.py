from unittest import TestCase

from .regressions import is_regression


class RegressionTestCase(TestCase):
    # This tests the concept of "what is a regression?", it _does not_ test for regressions in our code :-)

    def setUp(self):
        self.releases = ["a", "b", "c", "d", "e", "f", "g", "h"]

    def test_not_marked_as_fixed(self):
        # by definition: not marked as fixed means we cannot regress.
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=[],
            issues_at=[],
            current_issue_at="h"))

        # same but with observed issues
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=[],
            issues_at=["b", "c", "f"],
            current_issue_at="h"))

    def test_first_regression(self):
        # breakage in the very release marked as the fix
        self.assertTrue(is_regression(
            self.releases,
            fixed_at=["b"],
            issues_at=["a"],
            current_issue_at="b"))

        # breakage in a later release
        self.assertTrue(is_regression(
            self.releases,
            fixed_at=["b"],
            issues_at=["a"],
            current_issue_at="c"))

        # issues_at empty list (not expected to happen in real code, because how would you mark as fixed?)
        # just proceed as above.
        self.assertTrue(is_regression(
            self.releases,
            fixed_at=["b"],
            issues_at=[],
            current_issue_at="b"))

    def test_non_regressions(self):
        # breakage before the fix
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=["b"],
            issues_at=["a"],
            current_issue_at="a"))

        # breakage before the fix, but in a release the error had not been seen before.
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=["c"],
            issues_at=["a"],
            current_issue_at="b"))

    def test_observations_override_marked_resolutions(self):
        # if an issue has been marked as resolved but has also (presumably later on) been seen in reality to not have
        # been resolved, it is not resolved by that release. Hence, re-occurrence is not a (new) regression.
        self.assertFalse(is_regression(
            self.releases,
            fixed_at=["c"],
            issues_at=["c"],
            current_issue_at="c"))

    def test_longer_patterns(self):
        # breakage before the fix, but in a release the error had not been seen before.
        issues_at = ["a", "d"]
        fixed_at = ["c", "f"]

        self.assertEquals(False, is_regression(self.releases, fixed_at, issues_at, current_issue_at="a"))
        self.assertEquals(False, is_regression(self.releases, fixed_at, issues_at, current_issue_at="b"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, issues_at, current_issue_at="c"))
        self.assertEquals(False, is_regression(self.releases, fixed_at, issues_at, current_issue_at="d"))
        self.assertEquals(False, is_regression(self.releases, fixed_at, issues_at, current_issue_at="e"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, issues_at, current_issue_at="f"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, issues_at, current_issue_at="g"))
        self.assertEquals(True,  is_regression(self.releases, fixed_at, issues_at, current_issue_at="h"))

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
        issues_at = ["3.1.1", "4.0.1"]
        fixed_at = ["3.1.2", "4.0.2"]

        # In an ideal world: assertFalse
        self.assertTrue(is_regression(releases, fixed_at, issues_at, current_issue_at="4.0.0"))

        # Note that if we abandon sort-by-version, and instead order by time-of-creation, the unideal behavior goes away
        # automatically...
        releases = ["3.1.0", "3.1.1", "4.0.0", "4.0.1", "3.1.2", "4.0.2"]
        self.assertFalse(is_regression(releases, fixed_at, issues_at, current_issue_at="4.0.0"))

        # ... however, that introduces its own problems, such as not being able to mark the _lack_ of fixing in the
        # most recent major branch. (in the below, there is no fix on the 4.x branch reported, but a regression is
        # detected when 4.0.2 has the same problem it had in 4.0.1), i.e. the below should say 'assertFalse'
        self.assertTrue(is_regression(releases, ["3.1.2"], issues_at, current_issue_at="4.0.2"))
