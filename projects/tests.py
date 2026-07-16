from django.conf import settings
from django.apps import apps
from django.contrib.auth import get_user_model
from unittest.mock import patch

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from bugsink.utils import get_model_topography
from projects.forms import ProjectForm
from projects.models import Project, ProjectMembership, ProjectRole, ProjectVisibility
from events.factories import create_event
from issues.factories import get_or_create_issue, denormalized_issue_fields
from tags.models import store_tags
from issues.models import TurningPoint, TurningPointKind, Issue
from alerts.models import MessagingServiceConfig
from releases.models import Release
from files.models import File, FileMetadata
from events.usage import record_event_counts

from .tasks import get_model_topography_with_project_override

User = get_user_model()


class ProjectDeletionTestCase(TransactionTestCase):

    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(
            name="Test Project", stored_event_count=1, issue_count=1)  # 1, in prep. of the below
        self.issue, _ = get_or_create_issue(self.project)
        self.event = create_event(self.project, issue=self.issue)
        self.user = User.objects.create_user(username='test', password='test')

        TurningPoint.objects.create(
            project=self.project,
            issue=self.issue, triggering_event=self.event, timestamp=self.event.ingested_at,
            kind=TurningPointKind.FIRST_SEEN)

        MessagingServiceConfig.objects.create(project=self.project)
        ProjectMembership.objects.create(project=self.project, user=self.user)
        Release.objects.create(project=self.project, version="1.0.0")
        file = File.objects.create(checksum="a" * 40, filename="test.js.map", size=0)
        FileMetadata.objects.create(project=self.project, file=file)

        self.event.never_evict = True
        self.event.save()

        store_tags(self.event, self.issue, {"foo": "bar"})
        record_event_counts(self.project, self.issue, self.event.digested_at, self.event.digest_order)

    def test_delete_project(self):
        models = [apps.get_model(app_label=s.split('.')[0], model_name=s.split('.')[1].lower()) for s in [
                  "tags.EventTag",
                  "tags.IssueTag",
                  "tags.TagValue",
                  "tags.TagKey",
                  "issues.TurningPoint",
                  "events.IssueEventCountsPerHour",
                  "events.ProjectEventCountsPerHour",
                  "events.Event",
                  "issues.Grouping",
                  "files.FileMetadata",
                  "alerts.MessagingServiceConfig",
                  "projects.ProjectMembership",
                  "releases.Release",
                  "issues.Issue",
                  "projects.Project",
                  ]]

        for model in models:
            # test-the-test: make sure some instances of the models actually exist after setup
            self.assertTrue(model.objects.exists(), f"Some {model.__name__} should exist")

        # assertNumQueries() is brittle and opaque. But at least the brittle part is quick to fix (a single number) and
        # provides a canary for performance regressions.

        # correct for bugsink/transaction.py's select_for_update for non-sqlite databases
        correct_for_select_for_update = 1 if 'sqlite' not in settings.DATABASES['default']['ENGINE'] else 0

        with self.assertNumQueries(33 + correct_for_select_for_update):
            self.project.delete_deferred()

        # tests run w/ TASK_ALWAYS_EAGER, so in the below we can just check the database directly
        for model in models:
            self.assertFalse(model.objects.exists(), f"No {model.__name__}s should exist after issue deletion")

    def test_dependency_graphs(self):
        # tests for an implementation detail of defered deletion, namely 1 test that asserts what the actual
        # model-topography is, and one test that shows how we manually override it; this is to trigger a failure when
        # the topology changes (and forces us to double-check that the override is still correct).

        orig = get_model_topography()
        override = get_model_topography_with_project_override()

        def walk(topo, model_name):
            results = []
            for model, fk_name in topo[model_name]:
                results.append((model, fk_name))
                results.extend(walk(topo, model._meta.label))
            return results

        self.assertEqual(walk(orig, 'projects.Project'), [
            (apps.get_model('projects', 'ProjectMembership'), 'project'),
            (apps.get_model('releases', 'Release'), 'project'),
            (apps.get_model('issues', 'Issue'), 'project'),
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
            (apps.get_model('issues', 'Grouping'), 'project'),
            (apps.get_model('events', 'Event'), 'grouping'),
            (apps.get_model('issues', 'TurningPoint'), 'triggering_event'),
            (apps.get_model('tags', 'EventTag'), 'event'),
            (apps.get_model('issues', 'TurningPoint'), 'project'),
            (apps.get_model('files', 'FileMetadata'), 'project'),
            (apps.get_model('events', 'Event'), 'project'),
            (apps.get_model('issues', 'TurningPoint'), 'triggering_event'),
            (apps.get_model('tags', 'EventTag'), 'event'),
            (apps.get_model('events', 'ProjectEventCountsPerHour'), 'project'),
            (apps.get_model('events', 'IssueEventCountsPerHour'), 'project'),
            (apps.get_model('tags', 'TagKey'), 'project'),
            (apps.get_model('tags', 'TagValue'), 'key'),
            (apps.get_model('tags', 'EventTag'), 'value'),
            (apps.get_model('tags', 'IssueTag'), 'value'),
            (apps.get_model('tags', 'IssueTag'), 'key'),
            (apps.get_model('tags', 'TagValue'), 'project'),
            (apps.get_model('tags', 'EventTag'), 'value'),
            (apps.get_model('tags', 'IssueTag'), 'value'),
            (apps.get_model('tags', 'EventTag'), 'project'),
            (apps.get_model('tags', 'IssueTag'), 'project'),
            (apps.get_model('alerts', 'MessagingServiceConfig'), 'project'),
        ])

        self.assertEqual(walk(override, 'projects.Project'), [
            (apps.get_model('tags', 'EventTag'), 'project'),
            (apps.get_model('tags', 'IssueTag'), 'project'),
            (apps.get_model('tags', 'TagValue'), 'project'),
            (apps.get_model('tags', 'TagKey'), 'project'),
            (apps.get_model('issues', 'TurningPoint'), 'project'),
            (apps.get_model('events', 'IssueEventCountsPerHour'), 'project'),
            (apps.get_model('events', 'ProjectEventCountsPerHour'), 'project'),
            (apps.get_model('events', 'Event'), 'project'),
            (apps.get_model('issues', 'Grouping'), 'project'),
            (apps.get_model('alerts', 'MessagingServiceConfig'), 'project'),
            (apps.get_model('projects', 'ProjectMembership'), 'project'),
            (apps.get_model('releases', 'Release'), 'project'),
            (apps.get_model('issues', 'Issue'), 'project'),
            (apps.get_model('files', 'FileMetadata'), 'project'),
        ])


class ProjectFormTestCase(TransactionTestCase):

    def test_slug_is_read_only_on_edit(self):
        # Slug is exposed on the edit form for visibility but must not be editable: it's part of the issue's short
        # identifier, so changing it would break external references.
        project = Project.objects.create(name="Original Name", slug="original-slug")

        form = ProjectForm(
            data={
                "name": "Renamed",
                "slug": "tampered-slug",
                "visibility": ProjectVisibility.JOINABLE,
                "retention_max_event_count": 10000,
            },
            instance=project,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.slug, "original-slug")
        self.assertEqual(saved.name, "Renamed")


class ProjectListOpenIssueCountTestCase(TransactionTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="project-list-user", password="test")
        self.project = Project.objects.create(name="OpenCount Project", issue_count=3)
        ProjectMembership.objects.create(project=self.project, user=self.user, accepted=True)
        self.client.force_login(self.user)

        Issue.objects.create(
            project=self.project, digest_order=1, is_resolved=False, is_muted=False, **denormalized_issue_fields())
        Issue.objects.create(
            project=self.project, digest_order=2, is_resolved=True, is_muted=False, **denormalized_issue_fields())
        Issue.objects.create(
            project=self.project, digest_order=3, is_resolved=False, is_muted=True, **denormalized_issue_fields())

    def test_project_list_shows_open_issue_count_when_under_threshold(self):
        with patch.object(Issue.objects, "filter", wraps=Issue.objects.filter) as issue_filter:
            response = self.client.get("/projects/mine/")

        issue_filter.assert_called_once()
        self.assertContains(response, "1 open issues")

    def test_project_list_shows_zero_open_issues(self):
        Issue.objects.filter(project=self.project, is_resolved=False, is_muted=False).update(is_resolved=True)

        response = self.client.get("/projects/mine/")
        self.assertContains(response, "0 open issues")

    @patch("projects.views.OPEN_ISSUE_COUNT_SHOW_THRESHOLD", 2)
    def test_project_list_skips_open_issue_query_when_over_threshold(self):
        with patch.object(Issue.objects, "filter", wraps=Issue.objects.filter) as issue_filter:
            response = self.client.get("/projects/mine/")

        issue_filter.assert_not_called()
        self.assertContains(response, "many issues")
        self.assertNotContains(response, "open issues")


class ProjectScopedActionTestCase(TransactionTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="project-admin", password="test")
        self.project = Project.objects.create(name="owned")
        ProjectMembership.objects.create(
            project=self.project, user=self.user, role=ProjectRole.ADMIN, accepted=True)
        self.client.force_login(self.user)

    def test_member_remove_scopes_to_project(self):
        other_user = User.objects.create_user(username="other", password="test")
        other_project = Project.objects.create(name="other")
        other_membership = ProjectMembership.objects.create(project=other_project, user=other_user)

        response = self.client.post(
            f"/projects/{self.project.id}/members/",
            {"action": f"remove:{other_user.id}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProjectMembership.objects.filter(id=other_membership.id).exists())

    def test_alert_service_remove_scopes_to_project(self):
        other_project = Project.objects.create(name="other")
        other_service = MessagingServiceConfig.objects.create(project=other_project)

        response = self.client.post(
            f"/projects/{self.project.id}/alerts/",
            {"action": f"remove:{other_service.id}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(MessagingServiceConfig.objects.filter(id=other_service.id).exists())
