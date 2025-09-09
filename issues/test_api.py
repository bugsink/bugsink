from django.test import TestCase as DjangoTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from bsmain.models import AuthToken
from projects.models import Project
from issues.models import Issue
from issues.factories import get_or_create_issue
from events.factories import create_event_data


class IssueApiTests(DjangoTestCase):
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

    def test_list_by_project_default_desc(self):
        response = self.client.get(reverse("api:issue-list"), {"project": str(self.project.id)})
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids[0], str(self.issue1.id))
        self.assertEqual(ids[1], str(self.issue0.id))

    def test_list_by_project_order_asc(self):
        response = self.client.get(reverse("api:issue-list"), {"project": str(self.project.id), "order": "asc"})
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids[0], str(self.issue0.id))
        self.assertEqual(ids[1], str(self.issue1.id))

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
