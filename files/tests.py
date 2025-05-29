from uuid import UUID
import json
import gzip
from io import BytesIO
import os
from glob import glob
from django.contrib.auth import get_user_model

from compat.dsn import get_header_value
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project, ProjectMembership
from events.models import Event
from bsmain.models import AuthToken

from .models import File, FileMetadata


User = get_user_model()


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
