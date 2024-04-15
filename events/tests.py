from django.test import TestCase as DjangoTestCase
from django.contrib.auth.models import User
from projects.models import Project, ProjectMembership
from issues.models import Issue
from issues.factories import denormalized_issue_fields

from .factories import create_event


class ViewTests(DjangoTestCase):
    # we start with minimal "does this show something and not fully crash" tests and will expand from there.

    def setUp(self):
        self.user = User.objects.create_user(username='test', password='test')
        self.project = Project.objects.create()
        ProjectMembership.objects.create(project=self.project, user=self.user)
        self.issue = Issue.objects.create(project=self.project, **denormalized_issue_fields())
        self.event = create_event(self.project, self.issue)
        self.client.force_login(self.user)

    def test_event_download(self):
        response = self.client.get(f"/events/event/{self.event.pk}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertTrue("platform" in response.json())

    def test_event_raw(self):
        response = self.client.get(f"/events/event/{self.event.pk}/raw/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertTrue("platform" in response.json())

    def test_event_plaintext(self):
        response = self.client.get(f"/events/event/{self.event.pk}/plain/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
