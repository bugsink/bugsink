from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from projects.models import Project, ProjectMembership
from bsmain.models import AuthToken
from events.factories import create_event
from events.api_views import EventViewSet

from issues.factories import get_or_create_issue
from events.factories import create_event_data
from tags.models import store_tags
from events.usage import hour_bucket, record_event_counts


class EventApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(events_read=True)
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

    def test_list_search(self):
        matching = create_event(issue=self.issue, calculated_type="TypeError")
        other = create_event(issue=self.issue, calculated_type="ValueError")
        store_tags(matching, self.issue, {"environment": "production"})
        store_tags(other, self.issue, {"environment": "production"})
        create_event(issue=self.issue, calculated_type="TypeError")

        response = self.client.get(reverse("api:event-list"), {
            "issue": self.issue.id, "q": "TypeError environment:production"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([str(matching.id)], [row["id"] for row in response.json()["results"]])

    def test_list_blank_search(self):
        response = self.client.get(reverse("api:event-list"), {"issue": self.issue.id, "q": " \t "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([str(self.event.id)], [row["id"] for row in response.json()["results"]])

    def test_detail_not_found_is_404(self):
        url = reverse("api:event-detail", args=["00000000-0000-0000-0000-000000000000"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_detail_malformed_id_is_404(self):
        response = self.client.get(reverse("api:event-detail", args=["not-a-uuid"]))
        self.assertEqual(response.status_code, 404)

    def test_lookup_by_sdk_event_id(self):
        other_project = Project.objects.create(name="Other")
        other = create_event(project=other_project)
        other.event_id = self.event.event_id
        other.save()
        url = reverse("api:event-lookup")

        for project, event in [(self.project, self.event), (other_project, other)]:
            response = self.client.get(url, {"project": project.id, "event_id": event.event_id})
            detail = self.client.get(reverse("api:event-detail", args=[event.id]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), detail.json())

    def test_lookup_requires_event_id(self):
        response = self.client.get(reverse("api:event-lookup"), {"project": self.project.id})
        self.assertEqual(response.status_code, 400)
        self.assertEqual({"event_id": ["This field is required."]}, response.json())

    def test_lookup_not_found(self):
        for event_id in ["not-a-uuid", "00000000-0000-0000-0000-000000000000"]:
            response = self.client.get(reverse("api:event-lookup"), {
                "project": self.project.id, "event_id": event_id})
            self.assertEqual(response.status_code, 404)

    def test_lookup_hides_deleted_issue(self):
        self.issue.is_deleted = True
        self.issue.save()
        response = self.client.get(reverse("api:event-lookup"), {
            "project": self.project.id, "event_id": self.event.event_id})
        self.assertEqual(response.status_code, 404)

    def test_lookup_requires_personal_token_membership(self):
        user = get_user_model().objects.create_user(username="reader")
        membership = ProjectMembership.objects.create(project=self.project, user=user, accepted=True)
        token = AuthToken.objects.create(is_user_bound=True, user=user, events_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        params = {"project": self.project.id, "event_id": self.event.event_id}

        response = self.client.get(reverse("api:event-lookup"), params)
        self.assertEqual(response.status_code, 200)
        membership.delete()
        response = self.client.get(reverse("api:event-lookup"), params)
        self.assertEqual(response.status_code, 403)

    def test_stacktrace_malformed_id_is_404(self):
        response = self.client.get(reverse("api:event-stacktrace", args=["not-a-uuid"]))
        self.assertEqual(response.status_code, 404)
        self.assertIn("404 Not Found", response.content.decode("utf-8"))

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

    def test_project_bound_token_cannot_read_another_projects_events(self):
        other_project = Project.objects.create(name="Other event project")
        other_issue, _ = get_or_create_issue(other_project)
        other_event = create_event(issue=other_issue)
        token = AuthToken.objects.create(
            is_project_bound=True,
            project=self.project,
            events_read=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        own_detail = self.client.get(reverse("api:event-detail", args=[self.event.id]))
        foreign_list = self.client.get(reverse("api:event-list"), {"issue": other_issue.id})
        foreign_detail = self.client.get(reverse("api:event-detail", args=[other_event.id]))
        own_lookup = self.client.get(reverse("api:event-lookup"), {
            "project": self.project.id, "event_id": self.event.event_id})
        foreign_lookup = self.client.get(reverse("api:event-lookup"), {
            "project": other_project.id, "event_id": other_event.event_id})

        self.assertEqual(200, own_detail.status_code)
        self.assertEqual(200, own_lookup.status_code)
        self.assertEqual(403, foreign_list.status_code)
        self.assertEqual(403, foreign_detail.status_code)
        self.assertEqual(403, foreign_lookup.status_code)


class EventCountApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(issues_read=True, projects_read=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.project = Project.objects.create(name="Counts")
        self.issue, _ = get_or_create_issue(self.project)

    def test_issue_and_project_counts(self):
        end = hour_bucket(timezone.now())
        start = end - timezone.timedelta(hours=3)
        record_event_counts(self.project, self.issue, start - timezone.timedelta(hours=1), 1)
        record_event_counts(self.project, self.issue, start, 2)
        record_event_counts(self.project, self.issue, start, 3)
        record_event_counts(self.project, self.issue, start + timezone.timedelta(hours=2), 4)
        record_event_counts(self.project, self.issue, end, 5)
        other_issue, _ = get_or_create_issue(self.project, create_event_data(exception_type="Other"))
        record_event_counts(self.project, other_issue, start, 1)
        other_project = Project.objects.create(name="Other")
        foreign_issue, _ = get_or_create_issue(other_project)
        record_event_counts(other_project, foreign_issue, start, 1)

        for name, pk, expected in [
            ("api:issue-event-counts", self.issue.id, [2, 0, 1]),
            ("api:project-event-counts", self.project.id, [3, 0, 1]),
        ]:
            response = self.client.get(reverse(name, args=[pk]), {"start": start.isoformat(), "end": end.isoformat()})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(parse_datetime(result["start"]), start)
            self.assertEqual(parse_datetime(result["end"]), end)
            self.assertEqual(result["interval_seconds"], 3600)
            self.assertEqual([row["count"] for row in result["buckets"]], expected)
            self.assertEqual(
                [parse_datetime(row["timestamp"]) for row in result["buckets"]],
                [start + timezone.timedelta(hours=i) for i in range(3)],
            )

    def test_default_range(self):
        response = self.client.get(reverse("api:issue-event-counts", args=[self.issue.id]))
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(parse_datetime(result["end"]) - parse_datetime(result["start"]), timezone.timedelta(hours=24))
        self.assertEqual([row["count"] for row in result["buckets"]], [0] * 24)

    def test_invalid_ranges(self):
        end = hour_bucket(timezone.now())
        for start, stop in [
            (end, end),
            (end - timezone.timedelta(minutes=30), end),
            (end - timezone.timedelta(days=91), end),
            (end - timezone.timedelta(hours=1), end + timezone.timedelta(hours=2)),
        ]:
            response = self.client.get(reverse("api:issue-event-counts", args=[self.issue.id]), {
                "start": start.isoformat(), "end": stop.isoformat()})
            self.assertEqual(response.status_code, 400)


class EventPaginationTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create(events_read=True)
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

    def test_search_two_pages(self):
        project = Project.objects.create(name="Search")
        issue, _ = get_or_create_issue(project)
        events = []
        for _ in range(4):
            events.append(create_event(issue=issue, calculated_type="TypeError"))
            create_event(issue=issue, calculated_type="ValueError")

        r1 = self.client.get(reverse("api:event-list"), {"issue": issue.id, "q": "TypeError"})
        self.assertEqual(self._ids(r1), [str(events[3].id), str(events[2].id)])
        r2 = self.client.get(r1.json()["next"])
        self.assertEqual(self._ids(r2), [str(events[1].id), str(events[0].id)])
        self.assertIsNone(r2.json()["next"])
