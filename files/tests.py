from hashlib import sha1
from uuid import UUID
import json
import gzip
import io
from io import BytesIO
import os
from glob import glob
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import tag
from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase, override_settings
from django.core.management.base import CommandError
from django.core.management import call_command
from unittest.mock import patch

from compat.dsn import get_header_value
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from bugsink.transaction import immediate_atomic
from projects.models import Project, ProjectMembership
from events.models import Event
from bsmain.models import AuthToken
from bugsink.moreiterutils import batched
from bugsink.app_settings import override_settings as bugsink_override_settings

from .models import Chunk, File, FileMetadata
from .storage_registry import override_object_storages
from .tasks import assemble_file


User = get_user_model()


def get_test_object_storages(basepath, use_for_write):
    return {
        "file": {
            "local": {
                "STORAGE": "files.storage.ObjectFileStorage",
                "OPTIONS": {
                    "basepath": basepath,
                },
                "USE_FOR_WRITE": use_for_write,
            },
        },
    }


class FilesTests(TransactionTestCase):
    # Integration-test of file-upload and does-it-render-sourcemaps

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', password='test')
        self.project = Project.objects.create()
        ProjectMembership.objects.create(project=self.project, user=self.user)
        self.client.force_login(self.user)
        self.auth_token = AuthToken.objects.create()
        self.token_headers = {"Authorization": f"Bearer {self.auth_token.token}"}

    def test_auth_no_header(self):
        response = self.client.get("/api/0/organizations/anyorg/chunk-upload/", headers={})
        self.assertEqual(401, response.status_code)
        self.assertEqual({"error": "Authorization header not found"}, response.json())

    def test_auth_empty_header(self):
        response = self.client.get("/api/0/organizations/anyorg/chunk-upload/", headers={"Authorization": ""})
        self.assertEqual(401, response.status_code)
        self.assertEqual({"error": "Authorization header not found"}, response.json())

    def test_auth_overfull_header(self):
        response = self.client.get("/api/0/organizations/anyorg/chunk-upload/", headers={"Authorization": "Bearer a b"})
        self.assertEqual(401, response.status_code)
        self.assertEqual({"error": "Expecting 'Authorization: Token abc123...' but got 'Bearer a b'"}, response.json())

    def test_auth_wrong_token(self):
        response = self.client.get("/api/0/organizations/anyorg/chunk-upload/", headers={"Authorization": "Bearer xxx"})
        self.assertEqual(401, response.status_code)
        self.assertEqual({"error": "Invalid token"}, response.json())

    def test_assemble_file_to_object_storage(self):
        data = b"hello world"
        checksum = sha1(data, usedforsecurity=False).hexdigest()

        with tempfile.TemporaryDirectory() as tempdir:
            with override_object_storages(get_test_object_storages(tempdir, use_for_write=True)):
                Chunk.objects.create(checksum=checksum, size=len(data), data=data)

                file, created = assemble_file(checksum, [checksum], filename="hello.txt")

                self.assertTrue(created)
                self.assertEqual("local", file.storage_backend)
                self.assertEqual(data, file.get_raw_data())
                self.assertEqual(data, Path(tempdir, checksum).read_bytes())

    def test_migrate_file_to_and_from_object_storage(self):
        data = b"hello world"
        checksum = sha1(data, usedforsecurity=False).hexdigest()

        file = File.objects.create(checksum=checksum, filename="hello.txt", size=len(data), data=data)

        with tempfile.TemporaryDirectory() as tempdir:
            with override_object_storages(get_test_object_storages(tempdir, use_for_write=True)):
                call_command("migrate_to_current_objectstorage", "file", stdout=io.StringIO())

                file.refresh_from_db()
                self.assertEqual("local", file.storage_backend)
                self.assertEqual(b"", file.data)
                self.assertEqual(data, Path(tempdir, checksum).read_bytes())
                self.assertEqual(data, file.get_raw_data())

            with override_object_storages(get_test_object_storages(tempdir, use_for_write=False)):
                call_command("migrate_to_current_objectstorage", "file", stdout=io.StringIO())

                file.refresh_from_db()
                self.assertIsNone(file.storage_backend)
                self.assertEqual(data, file.get_raw_data())

    def test_migrate_file_hard_fails_when_source_storage_is_missing(self):
        checksum = "a" * 40
        file = File.objects.create(
            checksum=checksum,
            filename="hello.txt",
            size=0,
            data=b"",
            storage_backend="missing",
        )

        with self.assertRaisesMessage(
            CommandError,
            "Cannot migrate file objects; Unknown storages found for file: missing",
        ):
            call_command("migrate_to_current_objectstorage", "file", stdout=io.StringIO())

        file.refresh_from_db()
        self.assertEqual("missing", file.storage_backend)
        self.assertEqual(b"", file.data)

    def test_migrate_file_does_not_delete_source_before_commit(self):
        data = b"hello world"
        checksum = sha1(data, usedforsecurity=False).hexdigest()

        file = File.objects.create(
            checksum=checksum,
            filename="hello.txt",
            size=len(data),
            data=b"",
            storage_backend="source",
        )

        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            Path(source_dir, checksum).write_bytes(data)
            storages = {
                "file": {
                    "source": {
                        "STORAGE": "files.storage.ObjectFileStorage",
                        "OPTIONS": {"basepath": source_dir},
                    },
                    "target": {
                        "STORAGE": "files.storage.ObjectFileStorage",
                        "OPTIONS": {"basepath": target_dir},
                        "USE_FOR_WRITE": True,
                    },
                },
            }

            with override_object_storages(storages):
                with patch.object(File, "save", autospec=True, side_effect=Exception("boom")):
                    with self.assertRaisesMessage(Exception, "boom"):
                        call_command("migrate_to_current_objectstorage", "file", stdout=io.StringIO())

            file.refresh_from_db()
            self.assertEqual("source", file.storage_backend)
            self.assertTrue(Path(source_dir, checksum).exists())
            self.assertEqual(data, Path(source_dir, checksum).read_bytes())

    def test_cleanup_objectstorage_deletes_orphans(self):
        live_checksum = "a" * 40
        orphan_checksum = "b" * 40

        with tempfile.TemporaryDirectory() as tempdir:
            Path(tempdir, live_checksum).write_bytes(b"live")
            Path(tempdir, orphan_checksum).write_bytes(b"orphan")

            File.objects.create(
                checksum=live_checksum,
                filename="live.txt",
                size=4,
                data=b"",
                storage_backend="local",
            )

            with override_object_storages(get_test_object_storages(tempdir, use_for_write=False)):
                call_command("cleanup_objectstorage", "file", "local", stdout=io.StringIO())

            self.assertTrue(Path(tempdir, live_checksum).exists())
            self.assertFalse(Path(tempdir, orphan_checksum).exists())

    def test_external_file_cleanup_happens_after_commit(self):
        checksum = "a" * 40

        with tempfile.TemporaryDirectory() as tempdir:
            Path(tempdir, checksum).write_bytes(b"live")

            with override_object_storages(get_test_object_storages(tempdir, use_for_write=False)):
                file = File.objects.create(
                    checksum=checksum,
                    filename="live.txt",
                    size=4,
                    data=b"",
                    storage_backend="local",
                )

                with patch("files.models._cleanup_objects_on_storage") as cleanup:
                    with immediate_atomic():
                        file.delete()
                        cleanup.assert_not_called()

                    cleanup.assert_called_once_with([("file", checksum, "local")])

    def test_external_file_queryset_cleanup_is_not_run_on_rollback(self):
        checksum = "a" * 40

        with tempfile.TemporaryDirectory() as tempdir:
            Path(tempdir, checksum).write_bytes(b"live")

            with override_object_storages(get_test_object_storages(tempdir, use_for_write=False)):
                File.objects.create(
                    checksum=checksum,
                    filename="live.txt",
                    size=4,
                    data=b"",
                    storage_backend="local",
                )

                with patch("files.models._cleanup_objects_on_storage") as cleanup:
                    with self.assertRaises(Exception):
                        with immediate_atomic():
                            File.objects.filter(checksum=checksum).delete()
                            raise Exception("rollback")

                    cleanup.assert_not_called()

                self.assertTrue(File.objects.filter(checksum=checksum).exists())
                self.assertTrue(Path(tempdir, checksum).exists())

    def test_uuid_behavior_of_django(self):
        # test to check Django is doing the thing of converting various UUID-like things on "both sides" before
        # comparing. "this probably shouldn't be necessary" to test, but I'd rather have a test that proves it works
        # than to have to reason about it. Context: https://github.com/bugsink/bugsink/issues/105

        uuids = [
            "12345678123456781234567812345678",  # uuid_str_no_dashes
            "12345678-1234-5678-1234-567812345678",  # uuid_str_with_dashes
            UUID("12345678-1234-5678-1234-567812345678"),  # uuid_object
        ]

        file = File.objects.create(size=0)
        for create_with in uuids:
            FileMetadata.objects.all().delete()  # clean up before each test
            FileMetadata.objects.create(
                debug_id=create_with,
                file_type="source_map",
                file=file,
            )

            for test_with in uuids:
                fms = FileMetadata.objects.filter(debug_id__in=[test_with])
                self.assertEqual(1, fms.count())

    @tag("samples")
    def test_assemble_artifact_bundle(self):
        SAMPLES_DIR = os.getenv("SAMPLES_DIR", "../event-samples")
        event_samples = [SAMPLES_DIR + fn for fn in [
            "/bugsink/uglifyjs-minified-sourcemaps-in-bundle.json",
            "/bugsink/uglifyjs-minified-sourcemaps-in-bundle-multi-file.json",
            ]]

        artifact_bundles = glob(SAMPLES_DIR + "/*/artifact_bundles/*.zip")

        if len(artifact_bundles) != 2:
            raise Exception(f"Not all artifact bundles found in {SAMPLES_DIR}; I insist on having some to test with.")

        for filename in artifact_bundles:
            with open(filename, 'rb') as f:
                data = f.read()

            checksum = os.path.basename(filename).split(".")[0]

            gzipped_file = BytesIO(gzip.compress(data))
            gzipped_file.name = checksum

            # 1. chunk-upload
            response = self.client.post(
                "/api/0/organizations/anyorg/chunk-upload/",
                data={"file_gzip": gzipped_file},
                headers=self.token_headers,
            )

            self.assertEqual(
                200, response.status_code, "Error in %s: %s" % (
                    filename, response.content if response.status_code != 302 else response.url))

            # 2. artifactbundle/assemble
            data = {
                "checksum": checksum,
                "chunks": [
                    checksum,  # single-chunk upload, so this works
                ],
                "projects": [
                    "unused_for_now"
                ]
            }

            response = self.client.post(
                "/api/0/organizations/anyorg/artifactbundle/assemble/",
                json.dumps(data),
                content_type="application/json",
                headers=self.token_headers,
            )

            self.assertEqual(
                200, response.status_code, "Error in %s: %s" % (
                    filename, response.content if response.status_code != 302 else response.url))

        sentry_auth_header = get_header_value(f"http://{ self.project.sentry_key }@hostisignored/{ self.project.id }")
        for filename in event_samples:
            # minimal assertions on correctness in this loop; this will be caught by our general sample-testing
            with open(filename) as f:
                data = json.loads(f.read())

            response = self.client.post(
                f"/api/{ self.project.id }/store/",
                json.dumps(data),
                content_type="application/json",
                headers={
                    "X-Sentry-Auth": sentry_auth_header,
                },
            )
            self.assertEqual(
                200, response.status_code, "Error in %s: %s" % (
                    filename, response.content if response.status_code != 302 else response.url))

        for event_id, key_phrase in [
                ("af4d4093e2d548bea61683abecb8ee95", '<span class="font-bold">captureException.js</span> in <span class="font-bold">foo</span> line <span class="font-bold">15</span>'),  # noqa
                ("ed483af389554d9cac475049ed9f560f", '<span class="font-bold">captureException.js</span> in <span class="font-bold">foo</span> line <span class="font-bold">10</span>'),  # noqa
                    ]:

            event = Event.objects.get(event_id=event_id)

            url = f'/issues/issue/{ event.issue.id }/event/{ event.id }/'
            try:
                response = self.client.get(url)

                self.assertEqual(
                    200, response.status_code, response.content if response.status_code != 302 else response.url)

                self.assertTrue(key_phrase in response.content.decode('utf-8'))

            except Exception as e:
                # we want to know _which_ event failed, hence the raise-from-e here
                raise AssertionError("Error rendering event %s" % event.event_id) from e

    @tag("samples")
    def test_assemble_artifact_bundle_small_chunks(self):
        # Copy-paste of test_assemble_artifact_bundle, but checking _only_ that bundle assembly works with small chunks.
        SAMPLES_DIR = os.getenv("SAMPLES_DIR", "../event-samples")

        filename = SAMPLES_DIR + "/bugsink/artifact_bundles/51a5a327666cf1d11e23adfd55c3becad27ae769.zip"
        with open(filename, 'rb') as f:
            all_data = f.read()

        seen_checksums = []
        for data in batched(all_data, len(all_data) // 10):
            data = bytes(data)
            checksum = sha1(data).hexdigest()

            gzipped_file = BytesIO(gzip.compress(data))
            gzipped_file.name = checksum

            # 1. chunk-upload
            response = self.client.post(
                "/api/0/organizations/anyorg/chunk-upload/",
                data={"file_gzip": gzipped_file},
                headers=self.token_headers,
            )

            self.assertEqual(
                200, response.status_code, "Error in %s: %s" % (
                    filename, response.content if response.status_code != 302 else response.url))

            seen_checksums.append(checksum)

        checksum = os.path.basename(filename).split(".")[0]

        # 2. artifactbundle/assemble
        data = {
            "checksum": checksum,
            "chunks": seen_checksums,
            "projects": [
                "unused_for_now"
            ]
        }

        response = self.client.post(
            "/api/0/organizations/anyorg/artifactbundle/assemble/",
            json.dumps(data),
            content_type="application/json",
            headers=self.token_headers,
        )

        self.assertEqual(
            200, response.status_code, "Error in %s: %s" % (
                filename, response.content if response.status_code != 302 else response.url))


class EnterContextMixin:
    # https://docs.python.org/3.11/library/unittest.html#unittest.TestCase.enterContext but we support 3.10 too
    def enterContext(self, cm):
        result = cm.__enter__()

        def _exit(exc_type=None, exc=None, tb=None):
            cm.__exit__(exc_type, exc, tb)

        self.addCleanup(_exit)
        return result


class SentryCLITest(EnterContextMixin, LiveServerTestCase):
    # Test that the _actual_ sentry-cli tool can upload files to our chunk-upload endpoint, and that the files are
    # correctly assembled and processed.

    def setUp(self):
        super().setUp()
        auth = AuthToken.objects.create(description="test token")
        self.token = auth.token

        # sentry-cli asks _us_ for our own URL...
        self.enterContext(bugsink_override_settings(BASE_URL=self.live_server_url))

        # propagate exceptions so that we get the errors "from inside the server" instead of just sentry-cli reporting
        # about a 500 error (the setting just makes it end up on the output, it does not actually "escape" in such a
        # way that it fails the test itself (but sentry-cli will fail so we get both).
        self.enterContext(override_settings(DEBUG_PROPAGATE_EXCEPTIONS=True))
        self.tempdir = self.enterContext(tempfile.TemporaryDirectory())

    def _run(self, args):
        sp = subprocess.run(
            args,
            cwd=self.tempdir,
            env={
                "SENTRY_AUTH_TOKEN": self.token,
                "HOME": str(self.tempdir),  # avoid reading any config from the user's real home dir
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge stderr into stdout so we can see it in test failures
        )
        if sp.returncode != 0:
            raise Exception(f"Command {args} failed with output:\n{sp.stdout.decode('utf-8')}")

    def test_sentry_cli_upload(self):
        # Test-the-test (these things should live in your env, as per requirements.development.txt)
        sentry_cli = shutil.which("sentry-cli")
        identity = shutil.which("identity-sourcemap")
        assert sentry_cli, "sentry-cli not found on PATH (venv?)"
        assert identity, "identity-sourcemap not found on PATH (pip install ecma426)"

        ptempdir = Path(self.tempdir)
        js_path = ptempdir / "captureException.js"
        map_path = ptempdir / "captureException.js.map"

        js_path.write_text(MINIMAL_JS, encoding="utf-8")

        # generate sourcemap with identity-sourcemap
        self._run([identity, str(js_path)])
        assert map_path.exists(), "identity-sourcemap did not produce captureException.js.map"

        # sentry-cli sourcemaps inject
        self._run([sentry_cli, "sourcemaps", "inject", str(js_path), str(map_path)])

        injected_js = js_path.read_text(encoding="utf-8")
        assert "debugId=" in injected_js, injected_js[-500:]

        sourcemap = json.loads(map_path.read_text(encoding="utf-8"))
        assert ("debugId" in sourcemap) or ("debug_id" in sourcemap), sourcemap.keys()

        # sentry-cli sourcemaps upload
        self._run([
            sentry_cli,
            "--log-level=debug",
            "--url",
            self.live_server_url,
            "sourcemaps",
            "--org",
            "bugsinkhasnoorgs",
            "--project",
            "ignoredfornow",
            "upload",
            str(map_path),
        ])

        self.assertEqual(2, File.objects.count())
        self.assertTrue(File.objects.filter(filename="captureException.js.map").exists())
        self.assertTrue(File.objects.filter(filename__endswith=".zip").exists())

        # > When using sentry-cli or [..] Debug IDs are deterministically generated based on the source file contents.
        self.assertEqual(
            UUID('9b40e0f3-8084-5931-94d4-8d941780a177'),
            FileMetadata.objects.get(file__filename="captureException.js.map").debug_id)


MINIMAL_JS = """\
function bar() {
Sentry.captureException(new Error("Test Error"));
}

function foo() {
bar();
}

function captureException() {
foo();
}
"""
