import requests
import os
import inspect
import uuid
import json
import hashlib
import gzip
from io import BytesIO, StringIO
from glob import glob
from unittest import TestCase as RegularTestCase
from unittest.mock import call, patch
from datetime import datetime, timedelta, timezone
from zipfile import ZIP_DEFLATED, ZipFile

from django.test import TestCase as DjangoTestCase
from django.contrib.auth import get_user_model
from django.test import tag
from django.conf import settings
from django.apps import apps

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from bugsink.utils import get_model_topography
from projects.models import Project, ProjectMembership
from releases.models import create_release_if_needed
from events.factories import create_event, create_event_data
from bsmain.management.commands.send_json import Command as SendJsonCommand
from compat.dsn import get_header_value
from events.models import Event
from bsmain.models import AuthToken
from ingest.views import BaseIngestAPIView
from issues.factories import get_or_create_issue
from tags.models import store_tags
from tags.tasks import vacuum_tagvalues
from events.markdown_stacktrace import render_stacktrace_md
from files.models import File, FileMetadata
from events.usage import record_event_counts

from .models import (
    Issue, IssueStateManager, TurningPoint, TurningPointKind)
from .regressions import is_regression, is_regression_2, issue_is_regression
from .factories import denormalized_issue_fields
from .tasks import delete_issue_deps, delete_issue_deps_sync, get_model_topography_with_issue_override

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

    def test_marked_resolutions_override_observations(self):
        # Marking an issue as resolved in a release where it has already been seen means "resolved as of now".
        # A later event in that same release is therefore a regression.
        self.assertTrue(is_regression(
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
        timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
        create_release_if_needed(fresh(project), "", timestamp)

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
        timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
        create_release_if_needed(fresh(project), "", timestamp)

        # new issue is not a regression
        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        self.assertFalse(issue_is_regression(fresh(issue), ""))

        # resolve the issue, a reoccurrence is a regression
        IssueStateManager.resolve(issue)
        issue.save()

        # a new release happens
        create_release_if_needed(fresh(project), "1.0.0", timestamp)

        self.assertTrue(issue_is_regression(fresh(issue), "1.0.0"))

    def test_issue_is_regression_with_releases_resolve_by_latest(self):
        project = Project.objects.create()
        timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)

        create_release_if_needed(fresh(project), "1.0.0", timestamp)
        create_release_if_needed(fresh(project), "2.0.0", timestamp)

        # new issue is not a regression
        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        self.assertFalse(issue_is_regression(fresh(issue), "anything"))

        # resolve the by latest, reoccurrences of older releases are not regressions but occurrences by latest are
        IssueStateManager.resolve_by_latest(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertTrue(issue_is_regression(fresh(issue), "2.0.0"))

        # a new release happens, and the issue is seen there: also a regression
        create_release_if_needed(fresh(project), "3.0.0", timestamp)
        self.assertTrue(issue_is_regression(fresh(issue), "3.0.0"))

        # reopen the issue (as is done when a real regression is seen; or as would be done manually); nothing is a
        # regression once the issue is open
        IssueStateManager.reopen(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertFalse(issue_is_regression(fresh(issue), "2.0.0"))

    def test_issue_is_regression_with_releases_resolve_by_latest_after_observation(self):
        project = Project.objects.create()
        timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)

        create_release_if_needed(fresh(project), "1.0.0", timestamp)
        create_release_if_needed(fresh(project), "2.0.0", timestamp)

        issue = Issue.objects.create(
            project=project,
            events_at="2.0.0\n",
            **denormalized_issue_fields(),
        )

        IssueStateManager.resolve_by_latest(issue)
        issue.save()

        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertTrue(issue_is_regression(fresh(issue), "2.0.0"))

    def test_issue_is_regression_after_plain_resolve_on_release_project(self):
        project = Project.objects.create()
        timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)

        create_release_if_needed(fresh(project), "1.0.0", timestamp)
        create_release_if_needed(fresh(project), "1.1.0", timestamp)

        issue = Issue.objects.create(
            project=project,
            events_at="1.0.0\n",
            **denormalized_issue_fields(),
        )

        # Seen at 1.0, resolved at 1.0.
        IssueStateManager.resolve_by_release(issue, "1.0.0")
        issue.save()

        # Seen at 1.1, then resolved without pinning to a release.
        IssueStateManager.reopen(issue)
        issue.events_at += "1.1.0\n"
        IssueStateManager.resolve(issue)
        issue.save()

        self.assertEqual(fresh(issue).fixed_at, "1.0.0\n")
        self.assertTrue(fresh(issue).is_resolved_unconditionally)
        self.assertTrue(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertTrue(issue_is_regression(fresh(issue), "1.1.0"))

    def test_issue_is_regression_with_releases_resolve_by_next(self):
        project = Project.objects.create()
        timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)

        create_release_if_needed(fresh(project), "1.0.0", timestamp)
        create_release_if_needed(fresh(project), "2.0.0", timestamp)

        # new issue is not a regression
        issue = Issue.objects.create(project=project, **denormalized_issue_fields())
        self.assertFalse(issue_is_regression(fresh(issue), "anything"))

        # resolve the by next, reoccurrences of any existing releases are not regressions
        IssueStateManager.resolve_by_next(issue)
        issue.save()
        self.assertFalse(issue_is_regression(fresh(issue), "1.0.0"))
        self.assertFalse(issue_is_regression(fresh(issue), "2.0.0"))

        # a new release appears (as part of a new event); this is a regression
        create_release_if_needed(fresh(project), "3.0.0", timestamp)
        self.assertTrue(issue_is_regression(fresh(issue), "3.0.0"))

        # first-seen at any later release: regression
        create_release_if_needed(fresh(project), "4.0.0", timestamp)
        self.assertTrue(issue_is_regression(fresh(issue), "4.0.0"))

        # reopen cancels the "fixed in some future release" claim
        IssueStateManager.reopen(issue)
        issue.save()
        issue = fresh(issue)
        self.assertFalse(issue.is_resolved)
        self.assertFalse(issue.is_resolved_by_next_release)
        self.assertFalse(issue_is_regression(issue, "4.0.0"))


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

        issue, _ = get_or_create_issue(project)

        issue.unmute_on_volume_based_conditions = '[{"period": "day", "nr_of_periods": 1, "volume": 1}]'
        issue.is_muted = True
        issue.save()

        event = create_event(project, issue, project_digest_order=1)
        BaseIngestAPIView.count_issue_periods_and_act_on_it(issue, event, datetime.now(timezone.utc))
        issue.save()

        self.assertFalse(Issue.objects.get(id=issue.id).is_muted)
        self.assertEqual("[]", Issue.objects.get(id=issue.id).unmute_on_volume_based_conditions)

        self.assertEqual(1, send_unmute_alert.delay.call_count)

    @patch("issues.models.send_unmute_alert")
    def test_unmute_two_simultaneously_should_lead_to_one_alert(self, send_unmute_alert):
        project = Project.objects.create()

        issue, _ = get_or_create_issue(project)

        issue. unmute_on_volume_based_conditions = '''[
    {"period": "day", "nr_of_periods": 1, "volume": 1},
    {"period": "month", "nr_of_periods": 1, "volume": 1}
]'''
        issue.is_muted = True
        issue.save()

        event = create_event(project, issue, project_digest_order=1)
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
        self.project = Project.objects.create(name="test")
        ProjectMembership.objects.create(project=self.project, user=self.user, accepted=True)
        self.issue, _ = get_or_create_issue(self.project)
        self.event = create_event(self.project, self.issue, project_digest_order=1)
        self.client.force_login(self.user)

    def test_issue_list_view(self):
        response = self.client.get(f"/issues/{self.project.id}/")
        self.assertContains(response, self.issue.title())

    def test_pending_project_membership_cannot_view_issue_list(self):
        pending_user = User.objects.create_user(username='pending', password='test')
        ProjectMembership.objects.create(project=self.project, user=pending_user, accepted=False)
        self.client.force_login(pending_user)

        response = self.client.get(f"/issues/{self.project.id}/")

        self.assertEqual(response.status_code, 403)

    def test_issue_list_view_shows_24h_sparkline(self):
        now = datetime.now(timezone.utc)
        record_event_counts(self.project, self.issue, now, self.event.digest_order)
        record_event_counts(
            self.project, self.issue, datetime.now(timezone.utc) - timedelta(days=2), self.event.digest_order)

        response = self.client.get(f"/issues/{self.project.id}/")

        self.assertContains(response, "1 event in the past 24h")

    def test_issue_list_bulk_action_ignores_issues_from_other_projects(self):
        other_project = Project.objects.create(name="other")
        other_issue, _ = get_or_create_issue(other_project)

        response = self.client.post(
            f"/issues/{self.project.id}/",
            {"issue_ids[]": [str(other_issue.id)], "action": "resolve"},
        )

        self.assertEqual(response.status_code, 200)
        other_issue.refresh_from_db()
        self.assertFalse(other_issue.is_resolved)

    def test_global_issue_list_only_shows_issues_from_projects_the_user_can_access(self):
        self.issue.calculated_type = "AccessibleError"
        self.issue.calculated_value = "visible"
        self.issue.save(update_fields=["calculated_type", "calculated_value"])
        other_project = Project.objects.create(name="other")
        other_issue, _ = get_or_create_issue(other_project)
        other_issue.calculated_type = "InaccessibleError"
        other_issue.calculated_value = "hidden"
        other_issue.save(update_fields=["calculated_type", "calculated_value"])

        response = self.client.get("/issues/")

        self.assertContains(response, "AccessibleError")
        self.assertContains(response, self.issue.friendly_id())
        self.assertNotContains(response, "InaccessibleError")

    def test_global_issue_list_ignores_pending_project_memberships(self):
        pending_project = Project.objects.create(name="pending")
        ProjectMembership.objects.create(project=pending_project, user=self.user, accepted=False)
        pending_issue, _ = get_or_create_issue(pending_project)
        pending_issue.calculated_type = "PendingError"
        pending_issue.calculated_value = "hidden"
        pending_issue.save(update_fields=["calculated_type", "calculated_value"])

        response = self.client.get("/issues/")

        self.assertNotContains(response, "PendingError")

    def test_global_issue_list_bulk_action_ignores_issues_from_inaccessible_projects(self):
        other_project = Project.objects.create(name="other")
        other_issue, _ = get_or_create_issue(other_project)

        response = self.client.post(
            "/issues/",
            {"issue_ids[]": [str(other_issue.id)], "action": "resolve"},
        )

        self.assertEqual(response.status_code, 200)
        other_issue.refresh_from_db()
        self.assertFalse(other_issue.is_resolved)

    def test_issue_stacktrace(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{self.event.id}/")
        self.assertContains(response, self.issue.title())

    def test_issue_details(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{self.event.id}/details/")
        self.assertContains(response, self.issue.title())

    def test_issue_details_by_digest_order_with_tag_search(self):
        event = create_event(self.project, self.issue, project_digest_order=2)
        store_tags(event, self.issue, {"foo": "bar"})

        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{event.digest_order}/details/?q=foo:bar")

        self.assertContains(response, self.issue.title())

    def test_issue_event_views_do_not_show_events_from_other_projects(self):
        other_project = Project.objects.create(name="other")
        other_issue, _ = get_or_create_issue(other_project)
        other_event = create_event(other_project, other_issue, event_data={
            "event_id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": "python",
            "exception": {"values": [{"type": "OtherProjectError", "value": "other project stack value"}]},
            "request": {"headers": {"X-Secret": "other-project-header-value"}},
            "breadcrumbs": {"values": [{"category": "other-project", "message": "other project breadcrumb"}]},
        })

        cases = [
            (f"/issues/issue/{self.issue.id}/event/{other_event.id}/", "other project stack value"),
            (f"/issues/issue/{self.issue.id}/event/{other_event.id}/details/", "other-project-header-value"),
            (f"/issues/issue/{self.issue.id}/event/{other_event.id}/breadcrumbs/", "other project breadcrumb"),
        ]
        for url, marker in cases:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, marker)

    def test_issue_tags(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/tags/")
        self.assertContains(response, self.issue.title())

    def test_issue_sidebar_summarizes_long_release_lists(self):
        self.issue.events_at = "\n".join(f"2026.1.{i}.0" for i in range(10)) + "\n"
        self.issue.save()

        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{self.event.id}/")

        self.assertContains(response, "... «4 more» ...,")
        self.assertContains(response, "2026.1.0.0")
        self.assertContains(response, "2026.1.1.0")
        self.assertContains(response, "2026.1.2.0")
        self.assertContains(response, "2026.1.7.0")
        self.assertContains(response, "2026.1.8.0")
        self.assertContains(response, "2026.1.9.0")
        self.assertNotContains(response, "2026.1.4.0")

    def test_issue_grouping(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/grouping/")
        self.assertContains(response, self.issue.title())

    def test_issue_history(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/history/")
        self.assertContains(response, self.issue.title())

    def test_history_comment_edit_and_delete_scope_to_issue(self):
        other_issue, _ = get_or_create_issue(self.project, create_event_data(exception_type="OtherIssue"))
        other_comment = TurningPoint.objects.create(
            project=self.project,
            issue=other_issue,
            kind=TurningPointKind.MANUAL_ANNOTATION,
            user=self.user,
            comment="leave me alone",
            timestamp=datetime.now(timezone.utc),
        )

        response = self.client.post(
            f"/issues/issue/{self.issue.id}/history/comment/{other_comment.id}/",
            {"comment": "changed"},
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.post(f"/issues/issue/{self.issue.id}/history/comment/{other_comment.id}/delete/")
        self.assertEqual(response.status_code, 404)
        other_comment.refresh_from_db()
        self.assertEqual(other_comment.comment, "leave me alone")

    def test_issue_event_list(self):
        response = self.client.get(f"/issues/issue/{self.issue.id}/events/")
        self.assertContains(response, self.issue.title())

    @patch("events.utils.ecma426.loads")
    def test_use_sourcemap_in_stacktrace(self, mock_ecma426_loads):
        # Single integration test that covers all three sourcemap outcomes in one stacktrace:
        # * debug ID present but sourcemap missing
        # * sourcemap present but frame unmappable,
        # * sourcemap present and frame successfully mapped.
        missing_debug_id = uuid.uuid4()
        broken_debug_id = uuid.uuid4()
        good_debug_id = uuid.uuid4()

        broken_sourcemap = json.dumps({
            "version": 3,
            "x_kind": "broken",
            "sources": ["broken-source.ts"],
            "sourcesContent": ["broken line 1\nbroken line 2"],
            "names": [],
            "mappings": "",
        }).encode("utf-8")
        good_sourcemap = json.dumps({
            "version": 3,
            "x_kind": "good",
            "sources": ["good-source.ts"],
            "sourcesContent": [
                "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8\nline 9\nline 10\nline 11\nline 12"
            ],
            "names": [],
            "mappings": "",
        }).encode("utf-8")

        broken_file = File.objects.create(
            checksum=hashlib.sha1(broken_sourcemap).hexdigest(),
            filename="broken.js.map",
            size=len(broken_sourcemap),
            data=broken_sourcemap,
        )
        good_file = File.objects.create(
            checksum=hashlib.sha1(good_sourcemap).hexdigest(),
            filename="good.js.map",
            size=len(good_sourcemap),
            data=good_sourcemap,
        )
        FileMetadata.objects.create(file=broken_file, debug_id=broken_debug_id, file_type="source_map", data="{}")
        FileMetadata.objects.create(file=good_file, debug_id=good_debug_id, file_type="source_map", data="{}")

        class FakeMapping:
            source = "good-source.ts"
            original_line = 10
            name = "mappedFunction"

        class BrokenSourceMap:
            def lookup_left(self, *_args, **_kwargs):
                raise KeyError((10, 36758))

        class GoodSourceMap:
            def lookup_left(self, line, column):
                if (line, column) == (5, 12):
                    return FakeMapping()

        def fake_loads(data):
            sm = json.loads(data)
            if sm["x_kind"] == "broken":
                return BrokenSourceMap()
            if sm["x_kind"] == "good":
                return GoodSourceMap()
            raise AssertionError(f"unknown sourcemap marker: {sm.get('x_kind')}")

        mock_ecma426_loads.side_effect = fake_loads

        event_data = {
            "event_id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": "javascript",
            "exception": {
                "values": [{
                    "type": "Error",
                    "value": "test",
                    "stacktrace": {
                        "frames": [
                            {"filename": "missing.js", "lineno": 3, "colno": 9, "in_app": True},
                            {"filename": "broken.js", "lineno": 11, "colno": 36758, "in_app": True},
                            {"filename": "good.js", "lineno": 6, "colno": 12, "in_app": True},
                        ]
                    },
                }]
            },
            "debug_meta": {
                "images": [
                    {"type": "sourcemap", "code_file": "missing.js", "debug_id": str(missing_debug_id)},
                    {"type": "sourcemap", "code_file": "broken.js", "debug_id": str(broken_debug_id)},
                    {"type": "sourcemap", "code_file": "good.js", "debug_id": str(good_debug_id)},
                ]
            },
        }
        event = create_event(self.project, self.issue, event_data=event_data, project_digest_order=2)

        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{event.id}/")
        self.assertEqual(200, response.status_code)
        self.assertContains(response, f"No sourcemaps found for Debug ID {missing_debug_id}")
        self.assertContains(response, f"Error mapping (10, 36758) into sourcemap ({broken_debug_id})")
        self.assertContains(response, "broken.js")
        self.assertContains(response, "good-source.ts")
        self.assertContains(response, "mappedFunction</span> line <span class=\"font-bold\">11</span>")

    @patch("events.utils.ecma426.loads")
    def test_use_sourcemap_in_stacktrace_with_null_sources_content(self, mock_ecma426_loads):
        debug_id = uuid.uuid4()

        sourcemap = json.dumps({
            "version": 3,
            "sources": ["node_modules/dependency/index.js", "good-source.ts"],
            "sourcesContent": [
                None,
                "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8\nline 9\nline 10\nline 11\nline 12"
            ],
            "names": [],
            "mappings": "",
        }).encode("utf-8")

        sourcemap_file = File.objects.create(
            checksum=hashlib.sha1(sourcemap).hexdigest(),
            filename="good.js.map",
            size=len(sourcemap),
            data=sourcemap,
        )
        FileMetadata.objects.create(file=sourcemap_file, debug_id=debug_id, file_type="source_map", data="{}")

        class FakeMapping:
            source = "good-source.ts"
            original_line = 10
            name = "mappedFunction"

        class GoodSourceMap:
            def lookup_left(self, line, column):
                if (line, column) == (5, 12):
                    return FakeMapping()

        mock_ecma426_loads.return_value = GoodSourceMap()

        event_data = {
            "event_id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": "javascript",
            "exception": {
                "values": [{
                    "type": "Error",
                    "value": "test",
                    "stacktrace": {
                        "frames": [
                            {"filename": "good.js", "lineno": 6, "colno": 12, "in_app": True},
                        ]
                    },
                }]
            },
            "debug_meta": {
                "images": [
                    {"type": "sourcemap", "code_file": "good.js", "debug_id": str(debug_id)},
                ]
            },
        }
        event = create_event(self.project, self.issue, event_data=event_data, project_digest_order=2)

        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{event.id}/")
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "good-source.ts")
        self.assertContains(response, "mappedFunction</span> line <span class=\"font-bold\">11</span>")

    @patch("events.utils.ecma426.loads")
    def test_sourcemap_uploads_are_project_scoped_when_rendering_events(self, mock_ecma426_loads):
        debug_id = uuid.uuid4()
        auth_token = AuthToken.objects.create()
        other_project = Project.objects.create(name="other")
        ProjectMembership.objects.create(project=other_project, user=self.user, accepted=True)
        other_issue, _ = get_or_create_issue(other_project)
        sourcemap = json.dumps({
            "version": 3,
            "sources": ["other-project-source.ts"],
            "sourcesContent": ["other project source"],
            "names": [],
            "mappings": "",
        })
        bundle = BytesIO()
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps({
                "files": {
                    "~/app.js.map": {
                        "url": "~/app.js.map",
                        "type": "source_map",
                        "headers": {"debug-id": str(debug_id)},
                    },
                },
            }))
            zf.writestr("~/app.js.map", sourcemap)

        bundle_data = bundle.getvalue()
        checksum = hashlib.sha1(bundle_data, usedforsecurity=False).hexdigest()
        upload = BytesIO(gzip.compress(bundle_data))
        upload.name = checksum

        response = self.client.post(
            "/api/0/organizations/anyorg/chunk-upload/",
            data={"file_gzip": upload},
            headers={"Authorization": f"Bearer {auth_token.token}"},
        )
        self.assertEqual(200, response.status_code)

        response = self.client.post(
            "/api/0/organizations/anyorg/artifactbundle/assemble/",
            json.dumps({"checksum": checksum, "chunks": [checksum], "projects": [other_project.slug]}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token.token}"},
        )
        self.assertEqual(200, response.status_code)

        class FakeMapping:
            source = "other-project-source.ts"
            original_line = 0
            name = "mappedFunction"

        class GoodSourceMap:
            def lookup_left(self, line, column):
                if (line, column) == (5, 12):
                    return FakeMapping()

        mock_ecma426_loads.return_value = GoodSourceMap()

        event_data = {
            "event_id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": "javascript",
            "exception": {
                "values": [{
                    "type": "Error",
                    "value": "test",
                    "stacktrace": {"frames": [{"filename": "good.js", "lineno": 6, "colno": 12, "in_app": True}]},
                }]
            },
            "debug_meta": {
                "images": [{"type": "sourcemap", "code_file": "good.js", "debug_id": str(debug_id)}]
            },
        }

        # Positive case: the sourcemap works for the project it was uploaded to.
        other_event = create_event(other_project, other_issue, event_data=event_data, project_digest_order=1)
        response = self.client.get(f"/issues/issue/{other_issue.id}/event/{other_event.id}/")
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "other-project-source.ts")
        self.assertContains(response, "mappedFunction</span> line <span class=\"font-bold\">1</span>")

        # Negative case: the same debug ID does not resolve across project boundaries.
        event = create_event(self.project, self.issue, event_data=event_data, project_digest_order=2)

        response = self.client.get(f"/issues/issue/{self.issue.id}/event/{event.id}/")
        self.assertEqual(200, response.status_code)
        self.assertContains(response, f"No sourcemaps found for Debug ID {debug_id}")
        self.assertNotContains(response, "other project source")


@tag("samples")
@tag("integration")
class IntegrationTest(TransactionTestCase):

    def setUp(self):
        super().setUp()
        self.verbosity = self.get_verbosity()
        self.maxDiff = None  # show full diff on assertEqual failures

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
        ProjectMembership.objects.create(project=project, user=user, accepted=True)
        self.client.force_login(user)

        sentry_auth_header = get_header_value(f"http://{ project.sentry_key }@hostisignored/{ project.id }")

        # first, we ingest many issues
        command = SendJsonCommand()
        command.stdout = StringIO()
        command.stderr = StringIO()

        # the following may be used for faster debugging of individual failures:
        # for filename in ["...failing filename here..."]:

        SAMPLES_DIR = os.getenv("SAMPLES_DIR", "../event-samples")

        event_samples = glob(SAMPLES_DIR + "/*/*.json")
        known_broken = [SAMPLES_DIR + "/" + s.strip() for s in _readlines(SAMPLES_DIR + "/KNOWN-BROKEN")]

        if len(event_samples) == 0:
            raise Exception(f"No event samples found in {SAMPLES_DIR}; I insist on having some to test with.")

        if self.verbosity > 1:
            print(f"Found {len(event_samples)} event samples")

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

        for filename in event_samples:
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
                },
            )
            self.assertEqual(
                200, response.status_code, "Error in %s: %s" % (
                    filename, response.content if response.status_code != 302 else response.url))

        for event in Event.objects.all():
            render_stacktrace_md(event)  # just make sure this doesn't crash

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
                    raise AssertionError("Error rendering event") from e

    def test_render_stacktrace_md(self):
        user = User.objects.create_user(username='test', password='test')
        project = Project.objects.create(name="test")
        ProjectMembership.objects.create(project=project, user=user, accepted=True)
        self.client.force_login(user)

        sentry_auth_header = get_header_value(f"http://{ project.sentry_key }@hostisignored/{ project.id }")
        # event through the ingestion pipeline
        command = SendJsonCommand()
        command.stdout = StringIO()
        command.stderr = StringIO()

        SAMPLES_DIR = os.getenv("SAMPLES_DIR", "../event-samples")

        # a nice example because it has 4 kinds of frames (some missing source context, some missing local vars)
        filename = SAMPLES_DIR + "/bugsink/frames-with-missing-info.json"

        with open(filename) as f:
            data = json.loads(f.read())

        # leave as-is for reproducibility of the test
        # data["event_id"] =

        if not command.is_valid(data, filename):
            raise Exception("validatity check in %s: %s" % (filename, command.stderr.getvalue()))

        response = self.client.post(
            f"/api/{ project.id }/store/",
            json.dumps(data),
            content_type="application/json",
            headers={
                "X-Sentry-Auth": sentry_auth_header,
            },
        )
        self.assertEqual(
            200, response.status_code, "Error in %s: %s" % (
                filename, response.content if response.status_code != 302 else response.url))

        event = Event.objects.get(issue__project=project, event_id=data["event_id"])
        md = render_stacktrace_md(event, in_app_only=False, include_locals=True)

        self.assertEqual('''# CapturedStacktraceFo
4 kinds of frames

### manage.py:22 in `complete_with_both` [in-app]
  17 |         ) from exc
  18 |     execute_from_command_line(sys.argv)
  19 |
  20 |
  21 | if __name__ == '__main__':
▶ 22 |     main()

#### Locals

* `__name__` = `'__main__'`
* `__doc__` = `"Django's command-line utility for administrative tasks."`
* `__package__` = `None`
* `__loader__` = `<_frozen_importlib_external.SourceFileLoader object at 0x7fe00fb21810>`
* `__spec__` = `None`
* `__annotations__` = `{}`
* `__builtins__` = `<module 'builtins' (built-in)>`
* `__file__` = `'/mnt/datacrypt/dev/bugsink/manage.py'`
* `__cached__` = `None`
* `os` = `<module 'os' from '/usr/lib/python3.10/os.py'>`

### manage.py in `missing_code` [in-app]
_no source context available_

#### Locals

* `execute_from_command_line` = `<function execute_from_command_line at 0x7fe00ec72f80>`

### django/core/management/__init__.py:442 in `missing_vars` [in-app]
  437 |
  438 |
  439 | def execute_from_command_line(argv=None):
  440 |     """Run a ManagementUtility."""
  441 |     utility = ManagementUtility(argv)
▶ 442 |     utility.execute()

### django/core/management/__init__.py in `missing_everything` [in-app]
_no source context available_''', md)


class IssueDeletionTaskTestCase(RegularTestCase):

    @patch("issues.tasks.delay_on_commit")
    @patch("issues.tasks.delete_issue_deps_batch", return_value=True)
    def test_async_deletion_schedules_another_batch(self, delete_issue_deps_batch, delay_on_commit):
        delete_issue_deps("project", "issue")

        delete_issue_deps_batch.assert_called_once_with("project", "issue")
        delay_on_commit.assert_called_once_with(delete_issue_deps, "project", "issue")

    @patch("issues.tasks.delay_on_commit")
    @patch("issues.tasks.delete_issue_deps_batch", return_value=False)
    def test_async_deletion_stops_after_last_batch(self, delete_issue_deps_batch, delay_on_commit):
        delete_issue_deps("project", "issue")

        delete_issue_deps_batch.assert_called_once_with("project", "issue")
        delay_on_commit.assert_not_called()

    @patch("issues.tasks.delete_issue_deps_batch", side_effect=[True, True, False])
    def test_sync_deletion_runs_until_last_batch(self, delete_issue_deps_batch):
        delete_issue_deps_sync("project", "issue")

        self.assertEqual(
            [call("project", "issue"), call("project", "issue"), call("project", "issue")],
            delete_issue_deps_batch.call_args_list,
        )


class IssueDeletionTestCase(TransactionTestCase):

    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(
            name="Test Project", stored_event_count=1, issue_count=1)  # 1, in prep. of the below
        self.issue, _ = get_or_create_issue(self.project)
        self.event = create_event(self.project, issue=self.issue, project_digest_order=1)

        TurningPoint.objects.create(
            project=self.project,
            issue=self.issue, triggering_event=self.event, timestamp=self.event.ingested_at,
            kind=TurningPointKind.FIRST_SEEN)

        self.event.never_evict = True
        self.event.save()

        store_tags(self.event, self.issue, {"foo": "bar"})
        record_event_counts(self.project, self.issue, self.event.digested_at, self.event.digest_order)

    def test_delete_issue(self):
        models = [apps.get_model(app_label=s.split('.')[0], model_name=s.split('.')[1].lower()) for s in [
            'events.Event', 'events.IssueEventCountsPerHour', 'issues.Grouping', 'issues.TurningPoint', 'tags.EventTag',
            'issues.Issue', 'tags.IssueTag',
            'tags.TagValue',  # TagValue 'feels like' a vacuum_model (FKs reversed) but is cleaned up in `prune_orphans`
        ]]

        # see the note in `prune_orphans` about TagKey to understand why it's special.
        vacuum_models = [apps.get_model(app_label=s.split('.')[0], model_name=s.split('.')[1].lower())
                         for s in ['tags.TagKey']]

        for model in models + vacuum_models:
            # test-the-test: make sure some instances of the models actually exist after setup
            self.assertTrue(model.objects.exists(), f"Some {model.__name__} should exist")

        # assertNumQueries() is brittle and opaque. But at least the brittle part is quick to fix (a single number) and
        # provides a canary for performance regressions.

        # correct for bugsink/transaction.py's select_for_update for non-sqlite databases
        correct_for_select_for_update = 1 if 'sqlite' not in settings.DATABASES['default']['ENGINE'] else 0

        with self.assertNumQueries(22 + correct_for_select_for_update):
            self.issue.delete_deferred()

        # tests run w/ TASK_ALWAYS_EAGER, so in the below we can just check the database directly
        for model in models:
            self.assertFalse(model.objects.exists(), f"No {model.__name__}s should exist after issue deletion")

        for model in vacuum_models:
            # 'should' in quotes because this isn't so because we believe it's better if they did, but because the
            # code currently does not delete them.
            self.assertTrue(model.objects.exists(), f"Some {model.__name__}s 'should' exist after issue deletion")

        self.assertEqual(0, Project.objects.get().stored_event_count)
        self.assertEqual(0, Project.objects.get().issue_count)

        vacuum_tagvalues()
        # tests run w/ TASK_ALWAYS_EAGER, so any "delayed" (recursive) calls can be expected to have run

        for model in vacuum_models:
            self.assertFalse(model.objects.exists(), f"No {model.__name__}s should exist after vacuuming")

    def test_dependency_graphs(self):
        # tests for an implementation detail of defered deletion, namely 1 test that asserts what the actual
        # model-topography is, and one test that shows how we manually override it; this is to trigger a failure when
        # the topology changes (and forces us to double-check that the override is still correct).

        orig = get_model_topography()
        override = get_model_topography_with_issue_override()

        def walk(topo, model_name):
            results = []
            for model, fk_name in topo[model_name]:
                results.append((model, fk_name))
                results.extend(walk(topo, model._meta.label))
            return results

        self.assertEqual(walk(orig, 'issues.Issue'), [
            (apps.get_model('issues', 'Grouping'), 'issue'),
            (apps.get_model('events', 'Event'), 'grouping'),
            (apps.get_model('issues', 'TurningPoint'), 'triggering_event'),
            (apps.get_model('tags', 'EventTag'), 'event'),
            (apps.get_model('issues', 'TurningPoint'), 'issue'),
            (apps.get_model('events', 'Event'), 'issue'),
            (apps.get_model('issues', 'TurningPoint'), 'triggering_event'),
            (apps.get_model('tags', 'EventTag'), 'event'),
            (apps.get_model('events', 'IssueEventCountsPerHour'), 'issue'),
            (apps.get_model('tags', 'EventTag'), 'issue'),
            (apps.get_model('tags', 'IssueTag'), 'issue'),
        ])

        self.assertEqual(walk(override, 'issues.Issue'), [
            (apps.get_model('issues', 'TurningPoint'), 'issue'),
            (apps.get_model('events', 'IssueEventCountsPerHour'), 'issue'),
            (apps.get_model('tags', 'EventTag'), 'issue'),
            (apps.get_model('events', 'Event'), 'issue'),
            (apps.get_model('issues', 'Grouping'), 'issue'),
            (apps.get_model('tags', 'IssueTag'), 'issue'),
        ])
