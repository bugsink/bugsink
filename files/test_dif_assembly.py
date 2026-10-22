from hashlib import sha1
from io import BytesIO
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

from django.db import connection
from django.utils import timezone

from bugsink.app_settings import override_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from bsmain.models import AuthToken
from projects.models import Project

from .minidump import extract_dif_kind
from .models import Chunk, DifAssembly, File, FileMetadata
from .tasks import assemble_dif, vacuum_files_batch


class DifAssemblyTests(TransactionTestCase):
    # LLM-generated; not deeply inspected, but they do seem to cover the main cases we care about.

    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(name="test")
        token = AuthToken.objects.create(debug_files_upload=True)
        self.headers = {"Authorization": f"Bearer {token.token}"}
        self.debug_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        self.contents = b"""MODULE Linux x86_64 0123456789ABCDEF0123456789ABCDEF0 example
FILE 0 src/main.c
FUNC 10 10 0 main
10 10 6 0
"""
        self.checksum = sha1(self.contents, usedforsecurity=False).hexdigest()
        halfway = len(self.contents) // 2
        self.chunks = [self.contents[:halfway], self.contents[halfway:]]
        self.chunk_checksums = [sha1(chunk, usedforsecurity=False).hexdigest() for chunk in self.chunks]
        self.request_data = {
            self.checksum: {
                "name": "example.sym",
                "debug_id": str(self.debug_id),
                "chunks": self.chunk_checksums,
            },
        }

    @override_settings(FEATURE_MINIDUMPS=True)
    def assemble(self, project=None):
        project = project or self.project
        response = self.client.post(
            f"/api/0/projects/anyorg/{project.slug}/files/difs/assemble/",
            self.request_data,
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code)
        return response.json()[self.checksum]

    def upload_chunks(self):
        for checksum, contents in zip(self.chunk_checksums, self.chunks):
            upload = BytesIO(contents)
            upload.name = checksum
            response = self.client.post(
                "/api/0/organizations/anyorg/chunk-upload/",
                {"file": upload},
                headers=self.headers,
            )
            self.assertEqual(200, response.status_code)

    def test_upload_debug_file(self):
        self.assertEqual({"state": "not_found", "missingChunks": self.chunk_checksums}, self.assemble())
        self.upload_chunks()
        self.assemble()

        metadata = FileMetadata.objects.get(project=self.project, debug_id=self.debug_id, file_type="dbg")
        self.assertEqual("example.sym", metadata.file.filename)
        self.assertEqual(self.contents, metadata.file.get_raw_data())

        self.assertEqual({"state": "ok", "missingChunks": []}, self.assemble())
        self.assertEqual(1, File.objects.count())
        self.assertEqual(1, FileMetadata.objects.count())

    def test_existing_file_can_be_registered_for_another_project(self):
        self.upload_chunks()
        self.assemble()
        other_project = Project.objects.create(name="other")
        self.request_data[self.checksum]["chunks"] = []

        self.assemble(other_project)

        original = FileMetadata.objects.get(project=self.project, debug_id=self.debug_id, file_type="dbg")
        other = FileMetadata.objects.get(project=other_project, debug_id=self.debug_id, file_type="dbg")
        self.assertEqual(original.file_id, other.file_id)
        self.assertEqual(1, File.objects.count())

    def test_polling_waits_for_assembly_without_repeating_the_work(self):
        self.upload_chunks()

        with patch("files.views.assemble_dif.delay") as delay:
            self.assertEqual({"state": "assembling", "missingChunks": []}, self.assemble())
            self.assertEqual({"state": "assembling", "missingChunks": []}, self.assemble())
            self.assertEqual(1, delay.call_count)
            self.assertFalse(File.objects.exists())
            self.assertFalse(FileMetadata.objects.exists())

            assemble_dif(*delay.call_args.args)

            # A finished upload must be cheap to poll, even when its file is large or expensive to parse.
            with patch("files.tasks.extract_dif_kind", side_effect=AssertionError("Parsing during polling")):
                with patch.object(File, "get_raw_data", side_effect=AssertionError("Reading during polling")):
                    self.assertEqual({"state": "ok", "missingChunks": []}, self.assemble())
            self.assertEqual(1, delay.call_count)

        metadata = FileMetadata.objects.get(project=self.project, debug_id=self.debug_id, file_type="dbg")
        self.assertEqual(self.contents, metadata.file.get_raw_data())

    def test_failed_assembly_is_reported_without_retrying(self):
        self.upload_chunks()

        with patch("files.views.assemble_dif.delay") as delay:
            self.assemble()
            with override_settings(MAX_FILE_SIZE=len(self.contents) - 1):
                with self.assertLogs("bugsink.api", level="ERROR"):
                    assemble_dif(*delay.call_args.args)

            result = self.assemble()
            self.assertEqual("error", result["state"])
            self.assertIn("Could not assemble", result["detail"])
            self.assertEqual(result, self.assemble())
            self.assertEqual(1, delay.call_count)

        self.assertFalse(File.objects.exists())
        self.assertFalse(FileMetadata.objects.exists())

    def test_stored_file_is_not_ready_until_registered(self):
        self.upload_chunks()

        def parse(contents):
            self.assertTrue(File.objects.exists())
            self.assertFalse(FileMetadata.objects.exists())
            self.assertEqual({"state": "assembling", "missingChunks": []}, self.assemble())
            return extract_dif_kind(contents)

        with patch("files.views.assemble_dif.delay") as delay:
            self.assemble()
            with patch("files.tasks.extract_dif_kind", side_effect=parse):
                assemble_dif(*delay.call_args.args)
            self.assertEqual(1, delay.call_count)

        self.assertEqual({"state": "ok", "missingChunks": []}, self.assemble())

    def test_cleanup_allows_retrying_an_abandoned_upload(self):
        self.upload_chunks()

        with patch("files.views.assemble_dif.delay") as delay:
            self.assemble()
            old_task_args = delay.call_args.args
            DifAssembly.objects.update(created_at=timezone.now() - timedelta(days=2))

            with patch("files.tasks.VACUUM_FILES_BATCH_SIZE", 1):
                self.assertEqual((True, 1), vacuum_files_batch())
            self.assertFalse(DifAssembly.objects.exists())

            # A queued task whose upload has expired must not start processing its old chunks.
            assemble_dif(*old_task_args)
            self.assertFalse(File.objects.exists())

            self.assertEqual({"state": "assembling", "missingChunks": []}, self.assemble())
            self.assertEqual(2, delay.call_count)
            assemble_dif(*delay.call_args.args)
            self.assertEqual({"state": "ok", "missingChunks": []}, self.assemble())

    def test_evicted_file_is_not_reported_as_ready(self):
        self.upload_chunks()
        self.assemble()
        File.objects.get(checksum=self.checksum).delete()
        Chunk.objects.all().delete()

        self.assertEqual({"state": "not_found", "missingChunks": self.chunk_checksums}, self.assemble())

    def test_vacuum_can_evict_a_file_with_upload_status(self):
        self.upload_chunks()
        self.assemble()
        File.objects.update(accessed_at=timezone.now() - timedelta(days=91))

        vacuum_files_batch()

        self.assertFalse(File.objects.exists())
        self.assertFalse(FileMetadata.objects.exists())
        self.assertFalse(DifAssembly.objects.exists())

    def test_existing_file_can_be_registered_with_another_debug_id(self):
        self.upload_chunks()
        self.assemble()
        other_debug_id = UUID("fedcba98-7654-3210-fedc-ba9876543210")
        self.request_data[self.checksum]["debug_id"] = str(other_debug_id)

        self.assemble()

        original = FileMetadata.objects.get(project=self.project, debug_id=self.debug_id, file_type="dbg")
        other = FileMetadata.objects.get(project=self.project, debug_id=other_debug_id, file_type="dbg")
        self.assertEqual(original.file_id, other.file_id)

    def test_debug_file_parsing_does_not_hold_the_write_lock(self):
        self.upload_chunks()

        def parse(contents):
            self.assertFalse(connection.in_atomic_block)
            return extract_dif_kind(contents)

        with patch("files.tasks.extract_dif_kind", side_effect=parse):
            self.assemble()

        self.assertTrue(FileMetadata.objects.filter(project=self.project, debug_id=self.debug_id).exists())
