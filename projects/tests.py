from django.conf import settings
from django.apps import apps
from django.contrib.auth import get_user_model

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from bugsink.utils import get_model_topography
from projects.models import Project, ProjectMembership
from events.factories import create_event
from issues.factories import get_or_create_issue
from tags.models import store_tags
from issues.models import TurningPoint, TurningPointKind
from alerts.models import MessagingServiceConfig
from releases.models import Release

from .tasks import get_model_topography_with_project_override

User = get_user_model()


class ProjectDeletionTestCase(TransactionTestCase):

    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(name="Test Project", stored_event_count=1)  # 1, in prep. of the below
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

        self.event.never_evict = True
        self.event.save()

        store_tags(self.event, self.issue, {"foo": "bar"})

    def test_delete_project(self):
        models = [apps.get_model(app_label=s.split('.')[0], model_name=s.split('.')[1].lower()) for s in [
                  "tags.EventTag",
                  "tags.IssueTag",
                  "tags.TagValue",
                  "tags.TagKey",
                  "issues.TurningPoint",
                  "events.Event",
                  "issues.Grouping",
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

        with self.assertNumQueries(27 + correct_for_select_for_update):
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
            (apps.get_model('tags', 'EventTag'), 'issue'),
            (apps.get_model('tags', 'IssueTag'), 'issue'),
            (apps.get_model('issues', 'Grouping'), 'project'),
            (apps.get_model('events', 'Event'), 'grouping'),
            (apps.get_model('issues', 'TurningPoint'), 'triggering_event'),
            (apps.get_model('tags', 'EventTag'), 'event'),
            (apps.get_model('issues', 'TurningPoint'), 'project'),
            (apps.get_model('events', 'Event'), 'project'),
            (apps.get_model('issues', 'TurningPoint'), 'triggering_event'),
            (apps.get_model('tags', 'EventTag'), 'event'),
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
            (apps.get_model('events', 'Event'), 'project'),
            (apps.get_model('issues', 'Grouping'), 'project'),
            (apps.get_model('alerts', 'MessagingServiceConfig'), 'project'),
            (apps.get_model('projects', 'ProjectMembership'), 'project'),
            (apps.get_model('releases', 'Release'), 'project'),
            (apps.get_model('issues', 'Issue'), 'project')
        ])
