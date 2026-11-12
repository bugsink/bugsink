import importlib
import json
import tempfile
from uuid import uuid4
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from events.factories import create_event
from events.storage_registry import get_storage, override_event_storages
from projects.models import Project


class LegacyFileMetadataMigrationTests(TransactionTestCase):
    def migrate(self, name):
        executor = MigrationExecutor(connection)
        target = [("files", name)]
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def setUp(self):
        super().setUp()
        self.apps = self.migrate("0007_chunk_storage_backend")
        self.File = self.apps.get_model("files", "File")
        self.FileMetadata = self.apps.get_model("files", "FileMetadata")

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_event_references_rescue_legacy_metadata_without_replacing_scoped_uploads(self):
        project = Project.objects.create(name="first")
        other_project = Project.objects.create(name="second")
        deleted_project = Project.objects.create(name="deleted", is_deleted=True)
        debug_id, native_debug_id, unused_debug_id = uuid4(), uuid4(), uuid4()
        legacy_file = self.File.objects.create(checksum="a" * 40, filename="old", size=3, data=b"old")
        scoped_file = self.File.objects.create(checksum="b" * 40, filename="new", size=3, data=b"new")
        for file_type in ("source_map", "minified_source"):
            self.FileMetadata.objects.create(
                debug_id=debug_id, file_type=file_type, file=legacy_file, data='{"legacy": true}')
        for file_type in ("dbg", "src"):
            self.FileMetadata.objects.create(
                debug_id=native_debug_id, file_type=file_type, file=legacy_file, data="{}")
        self.FileMetadata.objects.create(
            debug_id=unused_debug_id, file_type="source_map", file=legacy_file, data="{}")
        scoped = self.FileMetadata.objects.create(
            project_id=project.pk, debug_id=debug_id, file_type="source_map", file=scoped_file, data="{}")
        payload = {"debug_meta": {"images": [
            {"type": "sourcemap", "debug_id": str(debug_id)},
            {"type": "elf", "debug_id": str(native_debug_id)},
            {"debug_id": "invalid"},
        ]}}
        for owner in (project, deleted_project):
            create_event(project=owner, event_data=payload)
        create_event(project=project, event_data=payload)

        with tempfile.TemporaryDirectory() as tempdir:
            with override_event_storages({"local": {
                "STORAGE": "events.storage.FileEventStorage", "OPTIONS": {"basepath": tempdir},
            }}):
                event = create_event(project=other_project, event_data={})
                event.storage_backend = "local"
                event.data = ""
                event.save()
                with get_storage("local").open(event.pk, "w") as f:
                    json.dump(payload, f)
                migration = importlib.import_module("files.migrations.0008_scope_legacy_file_metadata")
                with patch.object(migration, "EVENT_BATCH_SIZE", 1):
                    self.migrate("0008_scope_legacy_file_metadata")
                    with connection.schema_editor(atomic=False) as schema_editor:
                        migration.scope_legacy_file_metadata(self.apps, schema_editor)

        self.assertEqual(5, self.FileMetadata.objects.filter(project__isnull=True).count())
        self.assertEqual(8, self.FileMetadata.objects.filter(project__isnull=False).count())
        scoped.refresh_from_db()
        self.assertEqual(scoped_file.pk, scoped.file_id)
        self.assertFalse(self.FileMetadata.objects.filter(project_id=deleted_project.pk).exists())
        self.assertFalse(self.FileMetadata.objects.filter(project__isnull=False, debug_id=unused_debug_id).exists())
        rescued = self.FileMetadata.objects.get(
            project_id=other_project.pk, debug_id=debug_id, file_type="source_map")
        self.assertEqual(legacy_file.pk, rescued.file_id)
        self.assertEqual('{"legacy": true}', rescued.data)

    def test_cleanup_removes_all_projectless_metadata_and_preserves_files(self):
        project = Project.objects.create(name="test")
        file = self.File.objects.create(checksum="a" * 40, filename="old", size=3, data=b"old")
        referenced_debug_id, unused_debug_id = uuid4(), uuid4()
        for debug_id in (referenced_debug_id, unused_debug_id):
            for file_type in ("source_map", "minified_source", "dbg", "src"):
                self.FileMetadata.objects.create(debug_id=debug_id, file_type=file_type, file=file, data="{}")
        self.FileMetadata.objects.create(file=file, data="{}")
        create_event(project=project, event_data={"debug_meta": {"images": [
            {"debug_id": str(referenced_debug_id)},
        ]}})

        migration = importlib.import_module("files.migrations.0009_delete_projectless_file_metadata")
        with patch.object(migration, "BATCH_SIZE", 1):
            self.migrate("0009_delete_projectless_file_metadata")

        self.assertFalse(self.FileMetadata.objects.filter(project__isnull=True).exists())
        self.assertEqual(
            {"source_map", "minified_source", "dbg", "src"},
            set(self.FileMetadata.objects.filter(project_id=project.pk).values_list("file_type", flat=True)),
        )
        self.assertEqual({referenced_debug_id}, set(self.FileMetadata.objects.values_list("debug_id", flat=True)))
        self.assertEqual(b"old", bytes(self.File.objects.get(pk=file.pk).data))
