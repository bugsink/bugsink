from hashlib import sha1
from io import BytesIO
from uuid import UUID

from bugsink.app_settings import override_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from bsmain.models import AuthToken
from projects.models import Project

from .models import File, FileMetadata


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
