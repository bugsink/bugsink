import io
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.utils import timezone

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from events.factories import create_event
from events.models import Event
from files.models import Chunk, File, FileMetadata
from issues.factories import get_or_create_issue
from projects.models import Project
from tags.models import IssueTag, TagKey, TagValue, store_tags


class VacuumCommandTestCase(TransactionTestCase):
    # Auto-generated tests; not carefully reviewed but "at least this touches some code paths"

    def test_vacuum_defaults_to_all_cleanup_families(self):
        project = Project.objects.create(name="T")
        old = timezone.now() - timedelta(days=100)

        chunk = Chunk.objects.create(checksum="c" * 40, size=1, data=b"x")
        Chunk.objects.filter(id=chunk.id).update(created_at=old)

        orphan_key = TagKey.objects.create(project=project, key="orphan")
        TagValue.objects.create(project=project, key=orphan_key, value="orphan")

        issue, _ = get_or_create_issue(project)
        event = create_event(project, issue=issue)
        store_tags(event, issue, {"stale": "value"})
        event.delete_deferred()

        call_command("vacuum", stdout=io.StringIO())

        self.assertFalse(Chunk.objects.exists())
        self.assertFalse(IssueTag.objects.exists())
        self.assertFalse(TagValue.objects.exists())
        self.assertFalse(TagKey.objects.exists())

    @patch("files.tasks.VACUUM_FILES_BATCH_SIZE", 2)
    def test_vacuum_files_runs_inline_to_completion(self):
        old = timezone.now() - timedelta(days=100)

        old_chunks = [
            Chunk.objects.create(checksum=f"{i:040d}", size=1, data=b"x")
            for i in range(3)
        ]
        Chunk.objects.filter(id__in=[chunk.id for chunk in old_chunks]).update(created_at=old)

        recent_chunk = Chunk.objects.create(checksum="9" * 40, size=1, data=b"x")

        old_file = File.objects.create(checksum="a" * 40, filename="old.js.map", size=1, data=b"x")
        File.objects.filter(id=old_file.id).update(accessed_at=old)
        FileMetadata.objects.create(file=old_file, debug_id=uuid4(), file_type="source_map", data="{}")

        recent_file = File.objects.create(checksum="b" * 40, filename="recent.js.map", size=1, data=b"x")
        FileMetadata.objects.create(file=recent_file, debug_id=uuid4(), file_type="source_map", data="{}")

        call_command("vacuum", "--files", stdout=io.StringIO())

        self.assertEqual([recent_chunk.id], list(Chunk.objects.values_list("id", flat=True)))
        self.assertEqual([recent_file.id], list(File.objects.values_list("id", flat=True)))
        self.assertEqual([recent_file.id], list(FileMetadata.objects.values_list("file_id", flat=True)))

    @patch("tags.tasks.VACUUM_TAGS_BATCH_SIZE", 2)
    def test_vacuum_tags_runs_inline_to_completion(self):
        project = Project.objects.create(name="T")
        issue, _ = get_or_create_issue(project)

        used_key = TagKey.objects.create(project=project, key="used")
        used_value = TagValue.objects.create(project=project, key=used_key, value="still-used")
        IssueTag.objects.create(project=project, key=used_key, value=used_value, issue=issue, count=1)

        for i in range(3):
            orphan_key = TagKey.objects.create(project=project, key=f"orphan-{i}")
            TagValue.objects.create(project=project, key=orphan_key, value=f"value-{i}")

        call_command("vacuum", "--tags", stdout=io.StringIO())

        self.assertEqual([used_value.id], list(TagValue.objects.values_list("id", flat=True)))
        self.assertEqual([used_key.id], list(TagKey.objects.values_list("id", flat=True)))

    @patch("tags.tasks.VACUUM_EVENTLESS_ISSUETAGS_BATCH_SIZE", 2)
    @patch("tags.tasks.VACUUM_EVENTLESS_ISSUETAGS_INNER_BATCH_SIZE", 1)
    def test_vacuum_eventless_issuetags_runs_inline_to_completion(self):
        project = Project.objects.create(name="T")
        issue, _ = get_or_create_issue(project)
        event = create_event(project, issue=issue)
        store_tags(event, issue, {f"key-{i}": f"value-{i}" for i in range(3)})
        event.delete_deferred()

        call_command("vacuum", "--eventless-issuetags", stdout=io.StringIO())

        self.assertFalse(IssueTag.objects.exists())
        self.assertFalse(TagValue.objects.exists())

    def test_vacuum_old_events_runs_inline_to_completion(self):
        project = Project.objects.create(name="T")
        issue, _ = get_or_create_issue(project)
        old = timezone.now() - timedelta(days=11)
        recent = timezone.now() - timedelta(days=9)

        old_event = create_event(project, issue=issue, timestamp=old)
        create_event(project, issue=issue, timestamp=recent)

        project.stored_event_count = 2
        project.save(update_fields=["stored_event_count"])
        issue.stored_event_count = 2
        issue.save(update_fields=["stored_event_count"])

        call_command("vacuum", "--old-events", "--max-event-age-days", "10", stdout=io.StringIO())

        self.assertFalse(Event.objects.filter(pk=old_event.pk).exists())
        self.assertEqual(1, Event.objects.filter(project=project).count())
