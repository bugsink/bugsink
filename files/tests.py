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

    def test_assemble_artifact_bundle(self):
        SAMPLES_DIR = os.getenv("SAMPLES_DIR", "../event-samples")
        event_samples = [SAMPLES_DIR + fn for fn in ["/bugsink/uglifyjs-minified-sourcemaps-in-bundle.json"]]

        artifact_bundles = glob(SAMPLES_DIR + "/*/artifact_bundles/*.zip")

        if len(artifact_bundles) == 0:
            raise Exception(f"No artifact bundles found in {SAMPLES_DIR}; I insist on having some to test with.")

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

        for event in Event.objects.all():
            url = f'/issues/issue/{ event.issue.id }/event/{ event.id }/'
            try:
                # we just check for a 200; this at least makes sure we have no failing template rendering
                response = self.client.get(url)

                self.assertEqual(
                    200, response.status_code, response.content if response.status_code != 302 else response.url)

                # we could/should make this more general later; this is great for example nr.1:
                key_phrase = '<span class="font-bold">captureException</span> line <span class="font-bold">15</span>'
                self.assertTrue(key_phrase in response.content.decode('utf-8'))

            except Exception as e:
                # we want to know _which_ event failed, hence the raise-from-e here
                raise AssertionError("Error rendering event %s" % event.debug_info) from e
