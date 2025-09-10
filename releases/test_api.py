from django.test import TestCase as DjangoTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bsmain.models import AuthToken
from projects.models import Project
from releases.models import ordered_releases


class ReleaseApiTests(DjangoTestCase):
    def setUp(self):
        self.client = APIClient()
        token = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        self.project = Project.objects.create(name="RelProj")

    def _create(self, version, **extra):
        payload = {"project": self.project.id, "version": version}
        payload.update(extra)
        response = self.client.post(reverse("api:release-list"), payload, format="json")
        return response

    def test_list_requires_project(self):
        response = self.client.get(reverse("api:release-list"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual({"project": ["This field is required."]}, response.json())

    def test_list_uses_ordered_releases(self):
        # Create in arbitrary order
        self._create("1.0.0")
        self._create("1.0.0+build")
        self._create("1.0.1")

        response = self.client.get(reverse("api:release-list"), {"project": str(self.project.id)})
        self.assertEqual(response.status_code, 200)

        versions_from_api = [row["version"] for row in response.json()["results"]]
        versions_expected = [r.version for r in ordered_releases(project=self.project)]
        self.assertEqual(versions_from_api, versions_expected)

    def test_create_new_returns_201_and_detail_shape(self):
        response = self._create("1.2.3", timestamp="2024-01-01T00:00:00Z")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("id", body)

        # model-computed fields are present in response:
        self.assertIn("semver", body)
        self.assertIn("is_semver", body)
        self.assertIn("sort_epoch", body)

    def test_create_duplicate_returns_400(self):
        result1 = self._create("2.0.0")
        self.assertEqual(result1.status_code, 201)

        result2 = self._create("2.0.0")  # same project+version
        self.assertEqual(result2.status_code, 400)
        self.assertIn("version", result2.json())

    def test_create_allows_empty_version(self):
        response = self._create("")
        self.assertEqual(response.status_code, 201)

    def test_create_without_timestamp_is_allowed(self):
        response = self._create("3.0.0")
        self.assertEqual(response.status_code, 201)

    def test_detail_returns_readonly_fields(self):
        created = self._create("4.5.6")
        self.assertEqual(created.status_code, 201)
        release_id = created.json()["id"]

        response = self.client.get(reverse("api:release-detail", args=[release_id]))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("semver", body)
        self.assertIn("is_semver", body)
        self.assertIn("sort_epoch", body)

    def test_update_and_delete_methods_not_allowed(self):
        created = self._create("9.9.9")
        self.assertEqual(created.status_code, 201)
        release_id = created.json()["id"]
        detail_url = reverse("api:release-detail", args=[release_id])

        put_response = self.client.put(detail_url, {"version": "X"}, format="json")
        patch_response = self.client.patch(detail_url, {"version": "X"}, format="json")
        delete_response = self.client.delete(detail_url)

        self.assertEqual(put_response.status_code, 405)
        self.assertEqual(patch_response.status_code, 405)
        self.assertEqual(delete_response.status_code, 405)
