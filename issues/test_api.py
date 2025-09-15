from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from bsmain.models import AuthToken
from projects.models import Project
from issues.models import Issue
from issues.factories import get_or_create_issue
from events.factories import create_event_data

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

    def test_list_rejects_bad_order(self):
        response = self.client.get(reverse("api:issue-list"), {"project": str(self.project.id), "order": "sideways"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual({"order": ["Must be 'asc' or 'desc'."]}, response.json())

    def test_detail_by_id(self):
        url = reverse("api:issue-detail", args=[self.issue0.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.issue0.id))

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
        self.assertEqual(r.json(), {"sort": ["Must be 'digest_order' or 'last_seen'."]})


class IssuePaginationTests(TransactionTestCase):
    last_seen_deltas = [3, 1, 4, 0, 2]

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
            iss.save(update_fields=["digest_order", "last_seen"])
            issues.append(iss)
        return proj, issues

    def _ids(self, resp):
        return [row["id"] for row in resp.json()["results"]]

    def _idx_by_last_seen(self, issues, minutes):
        return issues[self.last_seen_deltas.index(minutes)].id

    def _idx_by_digest(self, issues, n):
        return issues[n - 1].id  # digest_order = n

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
