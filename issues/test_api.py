from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework.test import APIClient

from bsmain.models import AuthToken
from projects.models import Project, ProjectMembership
from releases.models import create_release_if_needed
from issues.models import Issue, TurningPoint, TurningPointKind
from issues.factories import get_or_create_issue
from events.factories import create_event, create_event_data
from tags.models import store_tags

from issues.api_views import IssueHistoryViewSet, IssueRelatedPagination, IssueViewSet


class IssueApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(
            issues_read=True,
            events_read=True,
            issues_comment=True,
            issues_triage=True,
            issues_delete=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        self.project = Project.objects.create(name="Test Project")

        # create two distinct issues for ordering tests (different grouping keys)
        data0 = create_event_data(exception_type="E0")
        data1 = create_event_data(exception_type="E1")

        self.issue0, _ = get_or_create_issue(project=self.project, event_data=data0)
        self.issue1, _ = get_or_create_issue(project=self.project, event_data=data1)

        # ensure deterministic last_seen ordering
        now = timezone.now()
        Issue.objects.filter(id=self.issue0.id).update(last_seen=now)
        Issue.objects.filter(id=self.issue1.id).update(last_seen=now + timezone.timedelta(seconds=1))
        self.issue0.refresh_from_db()
        self.issue1.refresh_from_db()

    def test_list_requires_project(self):
        response = self.client.get(reverse("api:issue-list"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual({"project": ["This field is required."]}, response.json())

    def test_list_by_project_default_asc(self):
        response = self.client.get(reverse("api:issue-list"), {"project": str(self.project.id)})
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids[0], str(self.issue0.id))
        self.assertEqual(ids[1], str(self.issue1.id))

    def test_list_by_project_order_desc(self):
        response = self.client.get(reverse("api:issue-list"), {"project": str(self.project.id), "order": "desc"})
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids[0], str(self.issue1.id))
        self.assertEqual(ids[1], str(self.issue0.id))

    def test_list_by_state(self):
        Issue.objects.filter(pk=self.issue1.pk).update(is_resolved=True)
        muted, _ = get_or_create_issue(self.project, create_event_data(exception_type="Muted"))
        Issue.objects.filter(pk=muted.pk).update(is_muted=True)

        for state, expected in [
            ("all", [self.issue0, self.issue1, muted]),
            ("open", [self.issue0]),
            ("unresolved", [self.issue0, muted]),
            ("resolved", [self.issue1]),
            ("muted", [muted]),
        ]:
            response = self.client.get(reverse("api:issue-list"), {"project": self.project.id, "state": state})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([str(issue.id) for issue in expected], [r["id"] for r in response.json()["results"]])

    def test_list_rejects_bad_state(self):
        response = self.client.get(reverse("api:issue-list"), {"project": self.project.id, "state": "unknown"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            {"state": ["Must be 'all', 'open', 'unresolved', 'resolved', or 'muted'."]}, response.json())

    def test_list_search(self):
        Issue.objects.filter(pk=self.issue0.pk).update(calculated_type="E0")
        Issue.objects.filter(pk=self.issue1.pk).update(calculated_type="E1")
        store_tags(create_event(issue=self.issue0), self.issue0, {"environment": "production"})
        store_tags(create_event(issue=self.issue1), self.issue1, {"environment": "production"})
        other_project = Project.objects.create(name="Other")
        other, _ = get_or_create_issue(other_project, create_event_data(exception_type="E0"))
        Issue.objects.filter(pk=other.pk).update(calculated_type="E0")
        store_tags(create_event(issue=other), other, {"environment": "production"})
        params = {"project": self.project.id, "q": "E0 environment:production", "state": "open"}

        response = self.client.get(reverse("api:issue-list"), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([str(self.issue0.id)], [r["id"] for r in response.json()["results"]])

        Issue.objects.filter(pk=self.issue0.pk).update(is_resolved=True)
        response = self.client.get(reverse("api:issue-list"), params)
        self.assertEqual(response.json()["results"], [])

    def test_list_blank_search(self):
        response = self.client.get(reverse("api:issue-list"), {"project": self.project.id, "q": " \t "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [str(self.issue0.id), str(self.issue1.id)], [row["id"] for row in response.json()["results"]])

    def test_list_by_digested_event_count(self):
        Issue.objects.filter(id=self.issue0.id).update(digested_event_count=10)
        Issue.objects.filter(id=self.issue1.id).update(digested_event_count=1)
        params = {"project": str(self.project.id), "sort": "digested_event_count"}

        response = self.client.get(reverse("api:issue-list"), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [str(self.issue1.id), str(self.issue0.id)],
            [row["id"] for row in response.json()["results"]],
        )

        response = self.client.get(reverse("api:issue-list"), params | {"order": "desc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [str(self.issue0.id), str(self.issue1.id)],
            [row["id"] for row in response.json()["results"]],
        )

    def test_list_rejects_bad_order(self):
        response = self.client.get(reverse("api:issue-list"), {"project": str(self.project.id), "order": "sideways"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual({"order": ["Must be 'asc' or 'desc'."]}, response.json())

    def test_detail_by_id(self):
        url = reverse("api:issue-detail", args=[self.issue0.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.issue0.id))
        self.assertEqual(response.json()["fixed_at"], [])
        self.assertEqual(response.json()["events_at"], [])
        self.assertIsNone(response.json()["unmute_after"])
        self.assertEqual(response.json()["unmute_on_volume_based_conditions"], [])

    def test_release_versions_in_list_and_detail(self):
        Issue.objects.filter(pk=self.issue0.pk).update(events_at="\n1.0.0\n1.1.0\n", fixed_at="1.1.0\n")
        detail = self.client.get(reverse("api:issue-detail", args=[self.issue0.id])).json()
        listing = self.client.get(reverse("api:issue-list"), {"project": self.project.id}).json()["results"][0]
        for result in [detail, listing]:
            self.assertEqual(result["events_at"], ["", "1.0.0", "1.1.0"])
            self.assertEqual(result["fixed_at"], ["1.1.0"])

    def test_friendly_id_alias(self):
        event = create_event(issue=self.issue0)
        friendly_id = self.issue0.friendly_id().lower()

        response = self.client.get(reverse("api:issue-detail", args=[friendly_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.issue0.id))
        self.assertEqual(response.json()["friendly_id"], self.issue0.friendly_id())

        response = self.client.post(reverse("api:issue-mute", args=[friendly_id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_muted"])

        response = self.client.get(reverse("api:event-list"), {"issue": friendly_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["id"], str(event.id))

    def test_detail_ignores_query_filters(self):
        url = reverse("api:issue-detail", args=[self.issue0.id])
        response = self.client.get(url, {"project": "00000000-0000-0000-0000-000000000000", "order": "asc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.issue0.id))

    def test_detail_404_on_is_deleted(self):
        Issue.objects.filter(id=self.issue0.id).update(is_deleted=True)
        url = reverse("api:issue-detail", args=[self.issue0.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        for action in ["tags", "grouping"]:
            response = self.client.get(reverse("api:issue-" + action, args=[self.issue0.id]))
            self.assertEqual(response.status_code, 404)

    def test_tag_values_and_counts(self):
        store_tags(create_event(issue=self.issue0), self.issue0, {"environment": "production", "release": "1.0"})
        store_tags(create_event(issue=self.issue0), self.issue0, {"environment": "production"})
        store_tags(create_event(issue=self.issue0), self.issue0, {"environment": "staging"})
        store_tags(create_event(issue=self.issue1), self.issue1, {"environment": "other"})

        response = self.client.get(reverse("api:issue-tags", args=[self.issue0.friendly_id()]), {"key": "environment"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [("environment", "production", 2), ("environment", "staging", 1)],
            [(row["key"], row["value"], row["count"]) for row in response.json()["results"]],
        )

    def test_grouping_keys(self):
        grouping = self.issue0.grouping_set.get()
        response = self.client.get(reverse("api:issue-grouping", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([{
            "id": grouping.id,
            "grouping_key": grouping.grouping_key,
            "grouping_mechanism": grouping.grouping_mechanism,
        }], response.json()["results"])

    def test_list_rejects_bad_sort(self):
        r = self.client.get(
            reverse("api:issue-list"),
            {"project": str(self.project.id), "sort": "nope"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            r.json(),
            {"sort": ["Must be 'digest_order', 'last_seen', or 'digested_event_count'."]},
        )

    def test_resolve(self):
        response = self.client.post(reverse("api:issue-resolve", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertTrue(self.issue0.is_resolved)
        self.assertTrue(self.issue0.is_resolved_unconditionally)
        self.assertEqual(self.issue0.fixed_at, "")
        self.assertEqual(response.json()["is_resolved"], True)
        self.assertEqual(response.json()["is_resolved_unconditionally"], True)

        turningpoint = TurningPoint.objects.get(issue=self.issue0)
        self.assertEqual(turningpoint.kind, TurningPointKind.RESOLVED)
        self.assertIsNone(turningpoint.user)

    def test_resolve_next(self):
        response = self.client.post(reverse("api:issue-resolve-next", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertTrue(self.issue0.is_resolved)
        self.assertTrue(self.issue0.is_resolved_by_next_release)

    def test_resolve_latest(self):
        create_release_if_needed(self.project, "1.0.0", timezone.now())

        response = self.client.post(reverse("api:issue-resolve-latest", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertTrue(self.issue0.is_resolved)
        self.assertFalse(self.issue0.is_resolved_unconditionally)
        self.assertEqual(self.issue0.fixed_at, "1.0.0\n")
        self.assertEqual(response.json()["fixed_at"], ["1.0.0"])

    def test_resolve_latest_allows_existing_occurrence(self):
        create_release_if_needed(self.project, "1.0.0", timezone.now())
        self.issue0.events_at = "1.0.0\n"
        self.issue0.save()

        response = self.client.post(reverse("api:issue-resolve-latest", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertTrue(self.issue0.is_resolved)
        self.assertFalse(self.issue0.is_resolved_unconditionally)
        self.assertEqual(self.issue0.fixed_at, "1.0.0\n")

    def test_resolve_latest_requires_releases(self):
        response = self.client.post(reverse("api:issue-resolve-latest", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Project has no releases."})

    def test_reopen(self):
        Issue.objects.filter(id=self.issue0.id).update(is_resolved=True, is_resolved_by_next_release=True)

        response = self.client.post(reverse("api:issue-reopen", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertFalse(self.issue0.is_resolved)
        self.assertFalse(self.issue0.is_resolved_unconditionally)
        self.assertFalse(self.issue0.is_resolved_by_next_release)
        self.assertEqual(response.json()["is_resolved"], False)
        self.assertEqual(response.json()["is_resolved_unconditionally"], False)
        self.assertEqual(response.json()["is_resolved_by_next_release"], False)

        turningpoint = TurningPoint.objects.get(issue=self.issue0)
        self.assertEqual(turningpoint.kind, TurningPointKind.REOPENED)

    def test_reopen_requires_resolved(self):
        response = self.client.post(reverse("api:issue-reopen", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Issue is not resolved."})

    def test_mute(self):
        response = self.client.post(reverse("api:issue-mute", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertTrue(self.issue0.is_muted)

        turningpoint = TurningPoint.objects.get(issue=self.issue0)
        self.assertEqual(turningpoint.kind, TurningPointKind.MUTED)

    def test_mute_for(self):
        response = self.client.post(
            reverse("api:issue-mute-for", args=[self.issue0.id]),
            {"period_name": "day", "nr_of_periods": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertTrue(self.issue0.is_muted)
        self.assertIsNotNone(self.issue0.unmute_after)
        self.assertEqual(parse_datetime(response.json()["unmute_after"]), self.issue0.unmute_after)

    def test_mute_until(self):
        response = self.client.post(
            reverse("api:issue-mute-until", args=[self.issue0.id]),
            {"period_name": "hour", "nr_of_periods": 1, "gte_threshold": 5},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertTrue(self.issue0.is_muted)
        self.assertEqual(
            self.issue0.unmute_on_volume_based_conditions,
            '[{"period": "hour", "nr_of_periods": 1, "volume": 5}]',
        )
        self.assertEqual(
            response.json()["unmute_on_volume_based_conditions"],
            [{"period": "hour", "nr_of_periods": 1, "volume": 5}],
        )

    def test_mute_for_accepts_non_ui_period(self):
        response = self.client.post(
            reverse("api:issue-mute-for", args=[self.issue0.id]),
            {"period_name": "minute", "nr_of_periods": 30},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertTrue(self.issue0.is_muted)
        self.assertIsNotNone(self.issue0.unmute_after)

    def test_mute_for_rejects_bad_period(self):
        response = self.client.post(
            reverse("api:issue-mute-for", args=[self.issue0.id]),
            {"period_name": "decade", "nr_of_periods": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("period_name", response.json())

    def test_mute_for_rejects_bad_period_count(self):
        response = self.client.post(
            reverse("api:issue-mute-for", args=[self.issue0.id]),
            {"period_name": "day", "nr_of_periods": -1},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("nr_of_periods", response.json())

    def test_mute_until_rejects_bad_threshold(self):
        response = self.client.post(
            reverse("api:issue-mute-until", args=[self.issue0.id]),
            {"period_name": "day", "nr_of_periods": 1, "gte_threshold": 0},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("gte_threshold", response.json())

    def test_unmute(self):
        Issue.objects.filter(id=self.issue0.id).update(is_muted=True)

        response = self.client.post(reverse("api:issue-unmute", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 200)

        self.issue0.refresh_from_db()
        self.assertFalse(self.issue0.is_muted)

    def test_invalid_action(self):
        Issue.objects.filter(id=self.issue0.id).update(is_resolved=True)

        response = self.client.post(reverse("api:issue-mute", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Issue is already resolved."})

    def test_delete(self):
        self.project.issue_count = 2
        self.project.save(update_fields=["issue_count"])

        response = self.client.delete(reverse("api:issue-detail", args=[self.issue0.id]))
        self.assertEqual(response.status_code, 204)

        self.project.refresh_from_db()
        # Snappea runs eagerly in tests, so delete_deferred() has completed by the time the response returns.
        self.assertFalse(Issue.objects.filter(id=self.issue0.id).exists())
        self.assertEqual(self.project.issue_count, 1)

    def test_unresolve_does_not_exist(self):
        response = self.client.post("/api/canonical/0/issues/%s/unresolve/" % self.issue0.id)
        self.assertEqual(response.status_code, 404)

    def test_create_comment(self):
        response = self.client.post(
            reverse("api:issue-comment-list"),
            {"issue": self.issue0.friendly_id(), "comment": "Needs a closer look."},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        turningpoint = TurningPoint.objects.get(issue=self.issue0)
        self.assertEqual(turningpoint.kind, TurningPointKind.MANUAL_ANNOTATION)
        self.assertEqual(turningpoint.project, self.project)
        self.assertEqual(turningpoint.comment, "Needs a closer look.")
        self.assertIsNone(turningpoint.user)

        self.assertEqual(response.json()["id"], turningpoint.id)
        self.assertEqual(response.json()["issue"], str(self.issue0.id))
        self.assertEqual(response.json()["project"], self.project.id)
        self.assertEqual(response.json()["user"], None)

        history = self.client.get(reverse("api:issue-history-list"), {"issue": self.issue0.friendly_id()})
        self.assertEqual(history.status_code, 200)
        self.assertEqual([response.json() | {
            "triggering_event": None,
            "user_display_name": None,
            "kind": "manual_annotation",
            "metadata": {},
        }], history.json()["results"])

    def test_create_comment_rejects_bad_issue_identifier(self):
        response = self.client.post(
            reverse("api:issue-comment-list"),
            {"issue": "not-an-issue", "comment": "Needs a closer look."},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"issue": ["Invalid issue identifier."]})

    def test_create_comment_rejects_missing_issue(self):
        response = self.client.post(
            reverse("api:issue-comment-list"),
            {"issue": "00000000-0000-0000-0000-000000000000", "comment": "Needs a closer look."},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"issue": ["Issue not found."]})

    def _create_history(self):
        now = timezone.now()
        return [
            TurningPoint.objects.create(
                project=self.project, issue=self.issue0, kind=TurningPointKind.FIRST_SEEN, timestamp=now),
            TurningPoint.objects.create(
                project=self.project, issue=self.issue0, kind=TurningPointKind.MUTED,
                metadata='{"mute_unconditionally": true}', timestamp=now + timezone.timedelta(seconds=1)),
            TurningPoint.objects.create(
                project=self.project, issue=self.issue0, kind=TurningPointKind.MANUAL_ANNOTATION,
                comment="Needs a closer look.", timestamp=now + timezone.timedelta(seconds=2)),
        ]

    def test_list_history(self):
        first_seen, muted, comment = self._create_history()
        TurningPoint.objects.create(
            project=self.project, issue=self.issue1, kind=TurningPointKind.FIRST_SEEN, timestamp=timezone.now())

        response = self.client.get(reverse("api:issue-history-list"), {"issue": self.issue0.friendly_id()})
        self.assertEqual(response.status_code, 200)

        results = response.json()["results"]
        self.assertEqual([comment.id, muted.id, first_seen.id], [row["id"] for row in results])
        self.assertEqual({
            "id": muted.id,
            "issue": str(self.issue0.id),
            "project": self.project.id,
            "triggering_event": None,
            "user": None,
            "user_display_name": None,
            "timestamp": results[1]["timestamp"],
            "kind": "muted",
            "comment": "",
            "metadata": {"mute_unconditionally": True},
        }, results[1])
        self.assertEqual("manual_annotation", results[0]["kind"])
        self.assertEqual("Needs a closer look.", results[0]["comment"])

    def test_list_history_authors(self):
        alice = get_user_model().objects.create_user(username="alice", first_name="Alice", last_name="Example")
        bob = get_user_model().objects.create_user(username="bob")
        for user in (alice, bob):
            TurningPoint.objects.create(
                project=self.project, issue=self.issue0, kind=TurningPointKind.MANUAL_ANNOTATION,
                user=user, comment="Looking into this.", timestamp=timezone.now())

        response = self.client.get(reverse("api:issue-history-list"), {"issue": str(self.issue0.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(bob.id, "bob"), (alice.id, "Alice Example")],
            [(row["user"], row["user_display_name"]) for row in response.json()["results"]],
        )

        alice.delete()
        response = self.client.get(reverse("api:issue-history-list"), {"issue": str(self.issue0.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(bob.id, "bob"), (None, None)],
            [(row["user"], row["user_display_name"]) for row in response.json()["results"]],
        )
        self.assertEqual("Looking into this.", response.json()["results"][1]["comment"])

    def test_list_history_order_asc(self):
        first_seen, muted, comment = self._create_history()

        response = self.client.get(reverse("api:issue-history-list"), {"issue": str(self.issue0.id), "order": "asc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([first_seen.id, muted.id, comment.id], [row["id"] for row in response.json()["results"]])

    def test_list_history_requires_issue(self):
        response = self.client.get(reverse("api:issue-history-list"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual({"issue": ["This field is required."]}, response.json())

    def test_list_history_requires_issues_read(self):
        token = AuthToken.objects.create(issues_comment=True, events_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = self.client.get(reverse("api:issue-history-list"), {"issue": str(self.issue0.id)})
        self.assertEqual(response.status_code, 403)

    def test_list_history_hides_deleted_issue(self):
        self._create_history()
        Issue.objects.filter(id=self.issue0.id).update(is_deleted=True)

        response = self.client.get(reverse("api:issue-history-list"), {"issue": str(self.issue0.id)})
        self.assertEqual(response.status_code, 404)

    def test_project_bound_token_cannot_read_or_change_another_projects_issues(self):
        other_project = Project.objects.create(name="Other project")
        other_issue, _ = get_or_create_issue(other_project, event_data=create_event_data(exception_type="Other"))
        token = AuthToken.objects.create(
            is_project_bound=True,
            project=self.project,
            issues_read=True,
            issues_triage=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        own_list = self.client.get(reverse("api:issue-list"), {"project": self.project.id})
        foreign_list = self.client.get(reverse("api:issue-list"), {"project": other_project.id})
        foreign_detail = self.client.get(reverse("api:issue-detail", args=[other_issue.id]))
        foreign_mute = self.client.post(reverse("api:issue-mute", args=[other_issue.id]))
        own_history = self.client.get(reverse("api:issue-history-list"), {"issue": self.issue0.id})
        foreign_history = self.client.get(reverse("api:issue-history-list"), {"issue": other_issue.id})

        self.assertEqual(200, own_list.status_code)
        self.assertEqual(200, own_history.status_code)
        self.assertNotIn(str(other_issue.id), [row["id"] for row in own_list.json()["results"]])
        self.assertEqual(403, foreign_list.status_code)
        self.assertEqual("This token is not allowed to access this project.", foreign_list.json()["detail"])
        self.assertEqual(403, foreign_detail.status_code)
        self.assertEqual(403, foreign_mute.status_code)
        self.assertEqual(403, foreign_history.status_code)
        for action in ["tags", "grouping"]:
            self.assertEqual(200, self.client.get(reverse("api:issue-" + action, args=[self.issue0.id])).status_code)
            self.assertEqual(403, self.client.get(reverse("api:issue-" + action, args=[other_issue.id])).status_code)
        other_issue.refresh_from_db()
        self.assertFalse(other_issue.is_muted)

    def test_project_bound_token_cannot_comment_on_another_projects_issue(self):
        other_project = Project.objects.create(name="Other comment project")
        other_issue, _ = get_or_create_issue(other_project, event_data=create_event_data(exception_type="Other"))
        token = AuthToken.objects.create(
            is_project_bound=True,
            project=self.project,
            issues_comment=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        own_response = self.client.post(
            reverse("api:issue-comment-list"),
            {"issue": self.issue0.id, "comment": "Own project"},
            format="json",
        )
        foreign_response = self.client.post(
            reverse("api:issue-comment-list"),
            {"issue": other_issue.id, "comment": "Foreign project"},
            format="json",
        )

        self.assertEqual(201, own_response.status_code)
        self.assertEqual(403, foreign_response.status_code)
        self.assertFalse(TurningPoint.objects.filter(issue=other_issue).exists())

    def test_personal_token_uses_current_project_membership(self):
        user = get_user_model().objects.create_user(username="issue-api-user")
        membership = ProjectMembership.objects.create(project=self.project, user=user, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, issues_read=True, issues_triage=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        self.assertEqual(200, self.client.get(reverse("api:issue-detail", args=[self.issue0.id])).status_code)
        history_url = reverse("api:issue-history-list")
        self.assertEqual(200, self.client.get(history_url, {"issue": self.issue0.id}).status_code)
        for action in ["tags", "grouping"]:
            self.assertEqual(200, self.client.get(reverse("api:issue-" + action, args=[self.issue0.id])).status_code)

        membership.accepted = False
        membership.save(update_fields=["accepted"])
        response = self.client.get(reverse("api:issue-detail", args=[self.issue0.id]))
        self.assertEqual(403, response.status_code)
        self.assertEqual(
            "The user bound to this token is not an accepted member of this project.",
            response.json()["detail"],
        )
        self.assertEqual(403, self.client.post(reverse("api:issue-mute", args=[self.issue0.id])).status_code)
        self.assertEqual(403, self.client.get(history_url, {"issue": self.issue0.id}).status_code)
        for action in ["tags", "grouping"]:
            self.assertEqual(403, self.client.get(reverse("api:issue-" + action, args=[self.issue0.id])).status_code)
        self.issue0.refresh_from_db()
        self.assertFalse(self.issue0.is_muted)

        membership.delete()
        self.assertEqual(403, self.client.get(reverse("api:issue-detail", args=[self.issue0.id])).status_code)
        self.assertEqual(403, self.client.get(history_url, {"issue": self.issue0.id}).status_code)

    def test_personal_superuser_is_still_limited_to_the_bound_project(self):
        other_project = Project.objects.create(name="Other superuser project")
        other_issue, _ = get_or_create_issue(other_project, event_data=create_event_data(exception_type="Other"))
        user = get_user_model().objects.create_superuser(username="api-superuser")
        token = AuthToken.objects.create(
            is_user_bound=True,
            user=user,
            is_project_bound=True,
            project=self.project,
            issues_read=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        own_response = self.client.get(reverse("api:issue-detail", args=[self.issue0.id]))
        foreign_response = self.client.get(reverse("api:issue-detail", args=[other_issue.id]))

        self.assertEqual(200, own_response.status_code)
        self.assertEqual(403, foreign_response.status_code)


class IssueTagPaginationTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(issues_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.old_size = IssueRelatedPagination.page_size
        IssueRelatedPagination.page_size = 2

    def tearDown(self):
        IssueRelatedPagination.page_size = self.old_size

    def test_tag_values_two_pages(self):
        issue, _ = get_or_create_issue()
        for value in ["production", "staging", "test"]:
            store_tags(create_event(issue=issue), issue, {"environment": value})
        store_tags(create_event(issue=issue), issue, {"release": "1.0"})

        r1 = self.client.get(reverse("api:issue-tags", args=[issue.id]), {"key": "environment"})
        self.assertEqual(["production", "staging"], [row["value"] for row in r1.json()["results"]])
        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(["test"], [row["value"] for row in r2.json()["results"]])
        self.assertIsNone(r2.json()["next"])


class IssueHistoryPaginationTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(issues_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.old_size = IssueHistoryViewSet.pagination_class.page_size
        IssueHistoryViewSet.pagination_class.page_size = 2

        project = Project.objects.create(name="P")
        self.issue, _ = get_or_create_issue(project=project)
        now = timezone.now()
        self.history = [
            TurningPoint.objects.create(
                project=project, issue=self.issue, kind=kind,
                timestamp=now + timezone.timedelta(seconds=seconds))
            for kind, seconds in [
                (TurningPointKind.FIRST_SEEN, 0),
                (TurningPointKind.NEXT_MATERIALIZED, 1),
                (TurningPointKind.REGRESSED, 1),
                (TurningPointKind.UNMUTED, 1),
                (TurningPointKind.MANUAL_ANNOTATION, 2),
            ]
        ]

    def tearDown(self):
        IssueHistoryViewSet.pagination_class.page_size = self.old_size

    def _ids(self, response):
        return [row["id"] for row in response.json()["results"]]

    def test_equal_timestamps_desc(self):
        r1 = self.client.get(reverse("api:issue-history-list"), {"issue": str(self.issue.id)})
        self.assertEqual(self._ids(r1), [self.history[4].id, self.history[3].id])

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(self._ids(r2), [self.history[2].id, self.history[1].id])

        r3 = self.client.get(r2.json()["next"])
        self.assertEqual(self._ids(r3), [self.history[0].id])
        self.assertIsNone(r3.json()["next"])

        previous = self.client.get(r3.json()["previous"])
        self.assertEqual(self._ids(previous), self._ids(r2))

    def test_equal_timestamps_asc(self):
        r1 = self.client.get(reverse("api:issue-history-list"), {"issue": str(self.issue.id), "order": "asc"})
        self.assertEqual(self._ids(r1), [self.history[0].id, self.history[1].id])

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(self._ids(r2), [self.history[2].id, self.history[3].id])

        r3 = self.client.get(r2.json()["next"])
        self.assertEqual(self._ids(r3), [self.history[4].id])
        self.assertIsNone(r3.json()["next"])

        previous = self.client.get(r3.json()["previous"])
        self.assertEqual(self._ids(previous), self._ids(r2))


class IssuePaginationTests(TransactionTestCase):
    last_seen_deltas = [3, 1, 4, 0, 2]
    event_counts = [4, 2, 5, 1, 3]

    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(issues_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.old_size = IssueViewSet.pagination_class.page_size
        IssueViewSet.pagination_class.page_size = 2

    def tearDown(self):
        IssueViewSet.pagination_class.page_size = self.old_size

    def _make_issues(self):
        proj = Project.objects.create(name="P")
        base = timezone.now().replace(microsecond=0)
        issues = []
        for i, delta in enumerate(self.last_seen_deltas):
            data = create_event_data(exception_type=f"E{i}")
            iss = get_or_create_issue(project=proj, event_data=data)[0]
            iss.digest_order = i + 1
            iss.last_seen = base + timezone.timedelta(minutes=delta)
            iss.digested_event_count = self.event_counts[i]
            iss.save(update_fields=["digest_order", "last_seen", "digested_event_count"])
            issues.append(iss)
        return proj, issues

    def _ids(self, resp):
        return [row["id"] for row in resp.json()["results"]]

    def _idx_by_last_seen(self, issues, minutes):
        return issues[self.last_seen_deltas.index(minutes)].id

    def _idx_by_digest(self, issues, n):
        return issues[n - 1].id  # digest_order = n

    def _idx_by_event_count(self, issues, count):
        return issues[self.event_counts.index(count)].id

    def test_digest_order_asc(self):
        proj, issues = self._make_issues()
        r1 = self.client.get(
            reverse("api:issue-list"),
            {"project": str(proj.id), "sort": "digest_order", "order": "asc"})

        self.assertEqual(self._ids(r1), [str(self._idx_by_digest(issues, 1)), str(self._idx_by_digest(issues, 2))])

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(self._ids(r2), [str(self._idx_by_digest(issues, 3)), str(self._idx_by_digest(issues, 4))])

    def test_digest_order_desc(self):
        proj, issues = self._make_issues()
        r1 = self.client.get(
            reverse("api:issue-list"), {"project": str(proj.id), "sort": "digest_order", "order": "desc"})

        self.assertEqual(self._ids(r1), [str(self._idx_by_digest(issues, 5)), str(self._idx_by_digest(issues, 4))])

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(self._ids(r2), [str(self._idx_by_digest(issues, 3)), str(self._idx_by_digest(issues, 2))])

    def test_last_seen_asc(self):
        proj, issues = self._make_issues()
        r1 = self.client.get(
            reverse("api:issue-list"), {"project": str(proj.id), "sort": "last_seen", "order": "asc"})

        self.assertEqual(
            self._ids(r1), [str(self._idx_by_last_seen(issues, 0)), str(self._idx_by_last_seen(issues, 1))])

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(self._ids(r2),
                         [str(self._idx_by_last_seen(issues, 2)), str(self._idx_by_last_seen(issues, 3))])

    def test_last_seen_desc(self):
        proj, issues = self._make_issues()

        r1 = self.client.get(
            reverse("api:issue-list"), {"project": str(proj.id), "sort": "last_seen", "order": "desc"})

        self.assertEqual(
            self._ids(r1), [str(self._idx_by_last_seen(issues, 4)), str(self._idx_by_last_seen(issues, 3))])

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(
            self._ids(r2), [str(self._idx_by_last_seen(issues, 2)), str(self._idx_by_last_seen(issues, 1))])

    def test_digested_event_count_asc(self):
        proj, issues = self._make_issues()
        r1 = self.client.get(
            reverse("api:issue-list"),
            {"project": str(proj.id), "sort": "digested_event_count", "order": "asc"},
        )

        self.assertEqual(
            self._ids(r1),
            [str(self._idx_by_event_count(issues, 1)), str(self._idx_by_event_count(issues, 2))],
        )

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(
            self._ids(r2),
            [str(self._idx_by_event_count(issues, 3)), str(self._idx_by_event_count(issues, 4))],
        )

    def test_digested_event_count_desc(self):
        proj, issues = self._make_issues()
        r1 = self.client.get(
            reverse("api:issue-list"),
            {"project": str(proj.id), "sort": "digested_event_count", "order": "desc"},
        )

        self.assertEqual(
            self._ids(r1),
            [str(self._idx_by_event_count(issues, 5)), str(self._idx_by_event_count(issues, 4))],
        )

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(
            self._ids(r2),
            [str(self._idx_by_event_count(issues, 3)), str(self._idx_by_event_count(issues, 2))],
        )
