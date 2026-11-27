from uuid import UUID

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project


class DebugIdMigrationTests(TransactionTestCase):
    def migrate(self, name):
        executor = MigrationExecutor(connection)
        target = [("files", name)]
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_artifacts_and_assemblies_keep_their_debug_ids(self):
        apps = self.migrate("0012_date_existing_assembly_errors")
        project = Project.objects.create(name="test")
        debug_id = UUID("1b504308-5f17-4da3-8552-1dd4740d1730")
        file = apps.get_model("files", "File").objects.create(checksum="a" * 40, size=0)
        metadata_model = apps.get_model("files", "FileMetadata")
        metadata = [metadata_model.objects.create(
            project_id=project.pk, file=file, debug_id=debug_id, file_type=file_type,
        ) for file_type in ("source_map", "dbg", "src")]
        assembly_model = apps.get_model("files", "DifAssembly")
        assembly = assembly_model.objects.create(
            project_id=project.pk, file=file, checksum=file.checksum, debug_id=debug_id, state="ok")
        without_id = assembly_model.objects.create(project_id=project.pk, checksum="b" * 40)

        apps = self.migrate("0014_normalize_debug_ids")

        objects = apps.get_model("files", "FileMetadata").objects
        self.assertEqual(
            {row.pk for row in metadata},
            set(objects.filter(project_id=project.pk, debug_id=str(debug_id)).values_list("pk", flat=True)),
        )
        migrated = apps.get_model("files", "DifAssembly").objects.get(
            project_id=project.pk, checksum=file.checksum, debug_id=str(debug_id))
        self.assertEqual(assembly.pk, migrated.pk)
        self.assertEqual(file.pk, migrated.file_id)
        self.assertEqual("ok", migrated.state)
        self.assertIsNone(apps.get_model("files", "DifAssembly").objects.get(pk=without_id.pk).debug_id)
