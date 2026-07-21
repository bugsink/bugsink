from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from bsmain.models import AuthToken
from projects.models import Project
from releases.models import create_release_if_needed
from issues.models import Issue, TurningPoint, TurningPointKind
from issues.factories import get_or_create_issue
from events.factories import create_event, create_event_data

from issues.api_views import IssueViewSet


class IssueApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create()
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


class IssuePaginationTests(TransactionTestCase):
    last_seen_deltas = [3, 1, 4, 0, 2]
    event_counts = [4, 2, 5, 1, 3]

    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create()
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
