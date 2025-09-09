from django.test import TestCase as DjangoTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from projects.models import Project
from bsmain.models import AuthToken
from events.factories import create_event
from issues.factories import get_or_create_issue


class EventApiTests(DjangoTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        self.project = Project.objects.create(name="Test Project")

        self.issue, _ = get_or_create_issue(project=self.project)
        self.event = create_event(issue=self.issue)

    def test_list_requires_scope(self):
        response = self.client.get(reverse("api:event-list"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual({'issue': ['This field is required.']}, response.json())

    def test_detail_by_id(self):
        url = reverse("api:event-detail", args=[self.event.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        self.assertEqual(detail["id"], str(self.event.id))
        self.assertIn("data", detail)

    def test_list_by_issue_is_light_payload(self):
        response = self.client.get(reverse("api:event-list"), {"issue": str(self.issue.id)})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("data", response.json()["results"][0])

    def test_detail_not_found_is_404(self):
        url = reverse("api:event-detail", args=["00000000-0000-0000-0000-000000000000"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_list_rejects_bad_order(self):
        response = self.client.get(reverse("api:event-list"), {"issue": str(self.issue.id), "order": "sideways"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual({'order': ["Must be 'asc' or 'desc'."]}, response.json())

    def test_list_order_default_desc(self):
        e0 = self.event
        e1 = create_event(issue=self.issue)
        response = self.client.get(reverse("api:event-list"), {"issue": str(self.issue.id)})
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.json()["results"]]
        self.assertEqual(ids[0], str(e1.id))
        self.assertEqual(ids[1], str(e0.id))

    def test_list_order_asc(self):
        e0 = self.event
        e1 = create_event(issue=self.issue)
        response = self.client.get(reverse("api:event-list"), {"issue": str(self.issue.id), "order": "asc"})
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.json()["results"]]
        self.assertEqual(ids[0], str(e0.id))
        self.assertEqual(ids[1], str(e1.id))
