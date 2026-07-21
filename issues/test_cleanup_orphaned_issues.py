import io
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from events.factories import create_event
from issues.factories import get_or_create_issue
from issues.models import Grouping, Issue
from issues.tasks import mark_orphaned_issues_batch, mark_orphaned_issues_sync
from projects.models import Project


class CleanupOrphanedIssuesCommandTestCase(TransactionTestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Cleanup")
        self.old_orphan = self.create_issue("OldOrphan", 20)
        self.recent_orphan = self.create_issue("RecentOrphan", 5)
        self.issue_with_event = self.create_issue("WithEvent", 20)
        create_event(self.project, issue=self.issue_with_event)
        self.issue_with_event.stored_event_count = 1
        self.issue_with_event.save(update_fields=["stored_event_count"])
        self.project.issue_count = 3
        self.project.stored_event_count = 1
        self.project.save(update_fields=["issue_count", "stored_event_count"])

    def create_issue(self, exception_type, age_days):
        issue, _ = get_or_create_issue(
            self.project,
            {"exception": {"values": [{"type": exception_type}]}},
        )
        seen = timezone.now() - timedelta(days=age_days)
        Issue.objects.filter(id=issue.id).update(first_seen=seen, last_seen=seen)
        issue.refresh_from_db()
        return issue

    def run_command(self, *args):
        stdout = io.StringIO()
        call_command("cleanup_orphaned_issues", *args, stdout=stdout, no_color=True)
        return stdout.getvalue()

    def test_command_deletes_old_orphans(self):
        old_grouping_id = self.old_orphan.grouping_set.get().id

        output = self.run_command("--days", "10")

        self.assertEqual("Orphaned issue cleanup complete.\n", output)
        self.assertFalse(Issue.objects.filter(id=self.old_orphan.id).exists())
        self.assertTrue(Issue.objects.filter(id=self.recent_orphan.id).exists())
        self.assertTrue(Issue.objects.filter(id=self.issue_with_event.id).exists())
        self.assertFalse(Grouping.objects.filter(id=old_grouping_id).exists())
        self.project.refresh_from_db()
        self.assertEqual(2, self.project.issue_count)

    def test_dry_run_does_not_delete(self):
        output = self.run_command("--days", "10", "--dry-run")

        self.assertEqual("Would delete 1 orphaned issue.\n", output)
        self.assertEqual(3, Issue.objects.count())

    def test_rejects_negative_days(self):
        with self.assertRaisesMessage(CommandError, "--days must be 0 or greater."):
            self.run_command("--days", "-1")


class MarkOrphanedIssuesTestCase(TransactionTestCase):
    def create_issue(self, project, exception_type):
        issue, _ = get_or_create_issue(
            project,
            {"exception": {"values": [{"type": exception_type}]}},
        )
        return issue

    @patch("issues.tasks.MARK_ORPHANED_ISSUES_BATCH_SIZE", 2)
    def test_marks_multiple_batches_and_updates_project_counts(self):
        project_a = Project.objects.create(name="A", issue_count=2)
        project_b = Project.objects.create(name="B", issue_count=1)
        issues = [
            self.create_issue(project_a, "A1"),
            self.create_issue(project_a, "A2"),
            self.create_issue(project_b, "B1"),
        ]

        mark_orphaned_issues_sync()

        self.assertEqual(3, Issue.objects.filter(is_deleted=True).count())
        self.assertFalse(Grouping.objects.filter(issue__in=issues, grouping_key_hash__isnull=False).exists())
        project_a.refresh_from_db()
        project_b.refresh_from_db()
        self.assertEqual(0, project_a.issue_count)
        self.assertEqual(0, project_b.issue_count)

    def test_batch_uses_a_constant_number_of_data_queries(self):
        project = Project.objects.create(name="Query count", issue_count=2)
        self.create_issue(project, "One")
        self.create_issue(project, "Two")

        with CaptureQueriesContext(connection) as queries:
            mark_orphaned_issues_batch()

        data_queries = [
            query["sql"] for query in queries
            if query["sql"].lstrip().upper().startswith(("SELECT", "UPDATE"))
            and "django_content_type" not in query["sql"]
        ]
        self.assertEqual(4, len(data_queries), data_queries)
