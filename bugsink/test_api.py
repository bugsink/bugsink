import unittest
from django.urls import reverse
from rest_framework.test import APIClient
from bsmain.models import AuthToken


class BearerAuthRouterTests(unittest.TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_ok_on_event_list(self):
        token = AuthToken.objects.create()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        resp = self.client.get(reverse("api:event-list"), {"issue": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(resp.status_code, 200)

    def test_missing_on_event_list(self):
        resp = self.client.get(reverse("api:event-list"))
        self.assertIn(resp.status_code, (401, 403))

    def test_invalid_on_event_list(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + "a" * 40)
        resp = self.client.get(reverse("api:event-list"))
        self.assertEqual(resp.status_code, 401)
