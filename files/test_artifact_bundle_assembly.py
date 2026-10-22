import json
from datetime import timedelta
from hashlib import sha1
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from django.utils import timezone

from bsmain.models import AuthToken
from bugsink.app_settings import override_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project

from .models import ArtifactBundleAssembly, Chunk, File, FileMetadata
from .tasks import assemble_artifact_bundle, vacuum_files_batch


class ArtifactBundleAssemblyTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(name="test")
        token = AuthToken.objects.create(debug_files_upload=True)
        self.headers = {"Authorization": f"Bearer {token.token}"}

        bundle = BytesIO()
        with ZipFile(bundle, "w") as bundle_zip:
            bundle_zip.writestr("manifest.json", '{"files": {}}')
        self.contents = bundle.getvalue()
        self.checksum = sha1(self.contents, usedforsecurity=False).hexdigest()
        Chunk.objects.create(checksum=self.checksum, size=len(self.contents), data=self.contents)
        self.request_data = {
            "checksum": self.checksum,
            "chunks": [self.checksum],
            "projects": [self.project.slug],
        }

    def assemble(self):
        response = self.client.post(
            "/api/0/organizations/anyorg/artifactbundle/assemble/",
            json.dumps(self.request_data),
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code)
        return response.json()

    def test_polling_reports_success_without_repeating_the_work(self):
        with patch("files.views.assemble_artifact_bundle.delay") as delay:
            self.assertEqual({"state": "created", "missingChunks": []}, self.assemble())
            self.assertEqual({"state": "created", "missingChunks": []}, self.assemble())
            self.assertEqual(1, delay.call_count)

            assemble_artifact_bundle(*delay.call_args.args)

            self.assertEqual({"state": "ok", "missingChunks": []}, self.assemble())
            self.assertEqual(1, delay.call_count)

    def test_oversized_bundle_is_reported_without_capturing_an_exception(self):
        with patch("files.views.assemble_artifact_bundle.delay") as delay:
            self.assemble()

            with override_settings(MAX_FILE_SIZE=len(self.contents) - 1):
                with patch("files.tasks.capture_or_log_exception") as capture:
                    assemble_artifact_bundle(*delay.call_args.args)
                capture.assert_not_called()

            result = self.assemble()
            self.assertEqual(
                {
                    "state": "error",
                    "detail": "Assembled file exceeds MAX_FILE_SIZE",
                    "missingChunks": [],
                },
                result,
            )
            self.assertEqual(result, self.assemble())
            self.assertEqual(1, delay.call_count)

        self.assertFalse(File.objects.exists())
        self.assertFalse(FileMetadata.objects.exists())

    def test_unexpected_failure_is_reported_and_captured(self):
        with patch("files.views.assemble_artifact_bundle.delay") as delay:
            self.assemble()

            with patch("files.tasks.process_artifact_bundle", side_effect=RuntimeError("broken")):
                with patch("files.tasks.capture_or_log_exception") as capture:
                    assemble_artifact_bundle(*delay.call_args.args)

            capture.assert_called_once()
            self.assertEqual(
                {
                    "state": "error",
                    "detail": "Could not assemble this artifact bundle. Check the server logs for details.",
                    "missingChunks": [],
                },
                self.assemble(),
            )

    def test_same_bundle_can_be_assembled_for_another_project(self):
        self.assemble()
        other_project = Project.objects.create(name="other")
        self.request_data["projects"] = [other_project.slug]

        with patch("files.views.assemble_artifact_bundle.delay") as delay:
            self.assertEqual({"state": "created", "missingChunks": []}, self.assemble())
            delay.assert_called_once_with(self.checksum, [self.checksum], [other_project.id])

    def test_cleanup_allows_retrying_an_abandoned_upload(self):
        with patch("files.views.assemble_artifact_bundle.delay") as delay:
            self.assemble()
            ArtifactBundleAssembly.objects.update(created_at=timezone.now() - timedelta(days=2))

            with patch("files.tasks.VACUUM_FILES_BATCH_SIZE", 1):
                self.assertEqual((True, 1), vacuum_files_batch())
            self.assertFalse(ArtifactBundleAssembly.objects.exists())

            self.assertEqual({"state": "created", "missingChunks": []}, self.assemble())
            self.assertEqual(2, delay.call_count)
