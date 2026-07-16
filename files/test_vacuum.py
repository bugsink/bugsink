from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.utils import timezone

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from files.models import File, FileMetadata
from files.tasks import vacuum_files_batch


class VacuumFilesBatchTestCase(TransactionTestCase):
    def _create_file(self, checksum, filename, size, accessed_at):
        file = File.objects.create(checksum=checksum, filename=filename, size=size, data=b"x" * size)
        FileMetadata.objects.create(file=file, debug_id=uuid4(), file_type="source_map", data="{}")
        File.objects.filter(id=file.id).update(accessed_at=accessed_at)
        file.refresh_from_db()
        return file

    @patch("files.tasks.VACUUM_FILES_BATCH_SIZE", 10)
    def test_vacuum_files_batch_is_noop_when_under_age_and_caps(self):
        self._create_file("a" * 40, "recent.js.map", 3, timezone.now() - timedelta(days=2))

        has_more_work, _ = vacuum_files_batch(file_max_days=90, max_file_count=2, max_file_bytes=10)

        self.assertFalse(has_more_work)
        self.assertEqual(1, File.objects.count())

    @patch("files.tasks.VACUUM_FILES_BATCH_SIZE", 10)
    def test_vacuum_files_batch_keeps_exactly_at_file_count_cap(self):
        now = timezone.now()

        oldest = self._create_file("b" * 40, "oldest.js.map", 1, now - timedelta(days=3))
        newest = self._create_file("c" * 40, "newest.js.map", 1, now - timedelta(days=1))

        has_more_work, _ = vacuum_files_batch(file_max_days=90, max_file_count=2)

        self.assertFalse(has_more_work)
        self.assertEqual(
            [oldest.id, newest.id],
            list(File.objects.order_by("accessed_at", "id").values_list("id", flat=True)),
        )

    @patch("files.tasks.VACUUM_FILES_BATCH_SIZE", 10)
    def test_vacuum_files_batch_deletes_minimum_oldest_prefix_for_byte_cap(self):
        now = timezone.now()

        middle = self._create_file("d" * 40, "middle.js.map", 4, now - timedelta(days=2))
        newest = self._create_file("e" * 40, "newest.js.map", 5, now - timedelta(days=1))
        self._create_file("f" * 40, "oldest.js.map", 3, now - timedelta(days=3))

        has_more_work, num_deleted = vacuum_files_batch(file_max_days=90, max_file_bytes=9)

        self.assertFalse(has_more_work)
        self.assertEqual(1, num_deleted)
        self.assertEqual(
            [middle.id, newest.id],
            list(File.objects.order_by("accessed_at", "id").values_list("id", flat=True)),
        )

    @patch("files.tasks.VACUUM_FILES_BATCH_SIZE", 10)
    def test_vacuum_files_batch_breaks_ties_by_id(self):
        accessed_at = timezone.now() - timedelta(days=1)

        first = self._create_file("1" * 40, "first.js.map", 1, accessed_at)
        second = self._create_file("2" * 40, "second.js.map", 1, accessed_at)

        has_more_work, num_deleted = vacuum_files_batch(file_max_days=90, max_file_count=1)

        self.assertFalse(has_more_work)
        self.assertEqual(1, num_deleted)
        self.assertEqual([second.id], list(File.objects.values_list("id", flat=True)))
        self.assertLess(first.id, second.id)

    @patch("files.tasks.VACUUM_FILES_BATCH_SIZE", 1)
    def test_vacuum_files_batch_deletes_before_reporting_more_work(self):
        self._create_file("a" * 40, "oldest.js.map", 1, timezone.now() - timedelta(days=3))
        newest = self._create_file("b" * 40, "newest.js.map", 1, timezone.now() - timedelta(days=1))

        has_more_work, num_deleted = vacuum_files_batch(file_max_days=90, max_file_count=1)

        self.assertTrue(has_more_work)
        self.assertEqual(1, num_deleted)
        self.assertEqual([newest.id], list(File.objects.values_list("id", flat=True)))
