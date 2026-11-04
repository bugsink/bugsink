from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from bsmain.models import AuthToken
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from mcpserver.models import OAuthAuthorizationCode, OAuthGrant
from mcpserver.oauth import sign_client

VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
CALLBACK = "http://localhost:5555/callback"


class TokenTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="alice")
        self.client = Client(enforce_csrf_checks=True)
        self.client_id = sign_client("Claude Code", ["http://localhost:1234/callback"])
        self.code = OAuthAuthorizationCode.objects.create(
            user=self.user, client_id=self.client_id, redirect_uri=CALLBACK, code_challenge=CHALLENGE,
            description="Claude Code (MCP)", capabilities=["issues:read"],
            expires_at=timezone.now() + timedelta(minutes=10))

    def exchange(self, **overrides):
        return self.client.post("/oauth/token", {
            "grant_type": "authorization_code", "code": self.code.code, "client_id": self.client_id,
            "redirect_uri": CALLBACK, "code_verifier": VERIFIER, **overrides})

    def refresh(self, refresh_token):
        return self.client.post("/oauth/token", {"grant_type": "refresh_token", "refresh_token": refresh_token})

    def test_exchange_issues_user_bound_token(self):
        response = self.exchange()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        body = response.json()
        self.assertEqual((body["token_type"], body["expires_in"]), ("Bearer", 3600))
        token = AuthToken.objects.get(token=body["access_token"])
        self.assertTrue(token.is_user_bound)
        self.assertEqual(token.user, self.user)
        self.assertEqual(token.capabilities, {"issues:read"})
        self.assertEqual(OAuthGrant.objects.get().refresh_token, body["refresh_token"])

    def test_code_is_single_use(self):
        self.exchange()
        response = self.exchange()
        self.assertEqual((response.status_code, response.json()), (400, {"error": "invalid_grant"}))

    def test_wrong_verifier(self):
        response = self.exchange(code_verifier="wrong")
        self.assertEqual((response.status_code, response.json()), (400, {"error": "invalid_grant"}))

    def test_tampered_client_id(self):
        response = self.exchange(client_id=self.client_id + "x")
        self.assertEqual((response.status_code, response.json()), (401, {"error": "invalid_client"}))

    def test_refresh_rotates_in_place(self):
        first = self.exchange().json()
        second = self.refresh(first["refresh_token"]).json()
        self.assertNotEqual(first["access_token"], second["access_token"])
        self.assertNotEqual(first["refresh_token"], second["refresh_token"])
        self.assertFalse(AuthToken.objects.filter(token=first["access_token"]).exists())
        self.assertEqual(AuthToken.objects.count(), 1)

    def test_replay_within_window_returns_same_tokens(self):
        first = self.exchange().json()
        second = self.refresh(first["refresh_token"]).json()
        replay = self.refresh(first["refresh_token"]).json()
        self.assertEqual((replay["access_token"], replay["refresh_token"]),
                         (second["access_token"], second["refresh_token"]))

    def test_replay_after_window_fails(self):
        first = self.exchange().json()
        self.refresh(first["refresh_token"])
        OAuthGrant.objects.update(previous_valid_until=timezone.now() - timedelta(seconds=1))
        response = self.refresh(first["refresh_token"])
        self.assertEqual((response.status_code, response.json()), (400, {"error": "invalid_grant"}))

    def test_refresh_for_inactive_user_deletes_token(self):
        first = self.exchange().json()
        self.user.is_active = False
        self.user.save()
        response = self.refresh(first["refresh_token"])
        self.assertEqual((response.status_code, response.json()), (400, {"error": "invalid_grant"}))
        self.assertFalse(AuthToken.objects.exists())

    def test_expired_grant_is_cleaned_up(self):
        self.exchange()
        OAuthGrant.objects.update(refresh_expires_at=timezone.now() - timedelta(seconds=1))
        self.client.post("/oauth/token", {"grant_type": "unknown"})
        self.assertFalse(AuthToken.objects.exists())

    def test_unsupported_grant_type(self):
        response = self.client.post("/oauth/token", {"grant_type": "password"})
        self.assertEqual((response.status_code, response.json()), (400, {"error": "unsupported_grant_type"}))
