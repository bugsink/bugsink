import unittest
from django.urls import reverse
from rest_framework.test import APIClient
from bsmain.models import AuthToken


class BearerAuthRouterTests(unittest.TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_ok_on_event_list(self):
        tok = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tok.token}")
        resp = self.client.get(reverse("api:event-list"))
        self.assertEqual(resp.status_code, 200)

    def test_missing_on_event_list(self):
        resp = self.client.get(reverse("api:event-list"))
        self.assertIn(resp.status_code, (401, 403))

    def test_invalid_on_event_list(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + "a" * 40)
        resp = self.client.get(reverse("api:event-list"))
        self.assertEqual(resp.status_code, 401)
