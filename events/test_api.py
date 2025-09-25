from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from projects.models import Project
from bsmain.models import AuthToken
from events.factories import create_event
from events.api_views import EventViewSet

from issues.factories import get_or_create_issue
from events.factories import create_event_data


class EventApiTests(TransactionTestCase):
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
        self.assertTrue("event_id" in detail["data"])

    def test_detail_includes_stacktrace_md_field(self):
        url = reverse("api:event-detail", args=[self.event.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        detail = response.json()

        self.assertIn("stacktrace_md", detail)
        self.assertIsInstance(detail["stacktrace_md"], str)
        self.assertTrue(len(detail["stacktrace_md"]) > 0)

        self.assertEqual("_No stacktrace available._", detail["stacktrace_md"])

    def test_stacktrace_action_returns_markdown(self):
        url = reverse("api:event-stacktrace", args=[self.event.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.assertTrue(response["Content-Type"].startswith("text/markdown"))
        body = response.content.decode("utf-8")
        self.assertTrue(len(body) > 0)

        self.assertEqual("_No stacktrace available._", body)

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


class EventPaginationTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.old_size = EventViewSet.pagination_class.page_size
        EventViewSet.pagination_class.page_size = 2

    def tearDown(self):
        EventViewSet.pagination_class.page_size = self.old_size

    def _make_events(self, issue, n=5):
        events = []
        for i in range(n):
            ev = create_event(issue=issue)
            events.append(ev)
        return events

    def _ids(self, resp):
        return [row["id"] for row in resp.json()["results"]]

    def test_digest_order_desc_two_pages(self):
        proj = Project.objects.create(name="P")
        issue = get_or_create_issue(project=proj, event_data=create_event_data(exception_type="root"))[0]
        events = self._make_events(issue, 5)

        # default (desc) → events 5,4 on page 1; 3,2 on page 2
        r1 = self.client.get(reverse("api:event-list"), {"issue": str(issue.id)})
        self.assertEqual(self._ids(r1), [str(events[4].id), str(events[3].id)])

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(self._ids(r2), [str(events[2].id), str(events[1].id)])

    def test_digest_order_asc_two_pages(self):
        proj = Project.objects.create(name="P2")
        issue = get_or_create_issue(project=proj, event_data=create_event_data(exception_type="root2"))[0]
        events = self._make_events(issue, 5)

        # asc → events 1,2 on page 1; 3,4 on page 2
        r1 = self.client.get(reverse("api:event-list"),
                             {"issue": str(issue.id), "order": "asc"})
        self.assertEqual(self._ids(r1), [str(events[0].id), str(events[1].id)])

        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(self._ids(r2), [str(events[2].id), str(events[3].id)])
