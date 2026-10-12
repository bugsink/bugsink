import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.test import override_settings as override_django_settings
from django.urls import reverse

from bugsink.app_settings import get_settings, override_settings, CB_ANYBODY
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from . import oidc
from .oidc import OIDCBackend


User = get_user_model()

DISCOVERY = {
    "issuer": "https://idp.example.org",
    "authorization_endpoint": "https://idp.example.org/auth",
    "token_endpoint": "https://idp.example.org/token",
    "userinfo_endpoint": "https://idp.example.org/userinfo",
    "jwks_uri": "https://idp.example.org/jwks",
    "end_session_endpoint": "https://idp.example.org/logout",
}

OIDC_ENABLED = override_django_settings(
    OIDC_ENABLED=True,
    OIDC_RP_CLIENT_ID="bugsink",
    OIDC_RP_CLIENT_SECRET="secret",
    OIDC_OP_DISCOVERY_URL="https://idp.example.org/.well-known/openid-configuration",
)


def json_response(data):
    return Mock(status_code=200, headers={"content-type": "application/json"}, json=Mock(return_value=data))


class FakeIdP:
    def __init__(self, userinfo, audience="bugsink"):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.userinfo = userinfo
        self.audience = audience
        self.nonce = None
        self.token_requests = []

    def get(self, url, **kwargs):
        if url == "https://idp.example.org/.well-known/openid-configuration":
            return json_response(DISCOVERY)
        if url == DISCOVERY["jwks_uri"]:
            jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
            return json_response({"keys": [{**jwk, "kid": "k1", "alg": "RS256"}]})
        if url == DISCOVERY["userinfo_endpoint"]:
            return json_response(self.userinfo)
        raise AssertionError(url)

    def post(self, url, data, **kwargs):
        assert url == DISCOVERY["token_endpoint"]
        self.token_requests.append(data)
        id_token = jwt.encode({
            "iss": DISCOVERY["issuer"],
            "aud": self.audience,
            "sub": "1234",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": self.nonce,
        }, self.key, algorithm="RS256", headers={"kid": "k1"})
        return json_response({"id_token": id_token, "access_token": "access-token"})


@OIDC_ENABLED
class OIDCTestCase(TransactionTestCase):
    def setUp(self):
        oidc._discovery_document = None
        get_settings()

    def login_via_idp(self, idp, next_url="/"):
        with patch("requests.get", side_effect=idp.get), patch("requests.post", side_effect=idp.post):
            response = self.client.get(reverse("oidc_authentication_init") + "?next=" + next_url)
            params = parse_qs(urlparse(response.url).query)
            idp.nonce = params["nonce"][0]
            return self.client.get(reverse("oidc_authentication_callback"), {"code": "c", "state": params["state"][0]})


class ClaimsTestCase(OIDCTestCase):
    def test_verify_claims(self):
        backend = OIDCBackend()
        self.assertFalse(backend.verify_claims({"email_verified": True}))
        self.assertFalse(backend.verify_claims({"email": "a@example.org"}))
        self.assertFalse(backend.verify_claims({"email": "a@example.org", "email_verified": False}))
        self.assertTrue(backend.verify_claims({"email": "a@example.org", "email_verified": True}))
        self.assertTrue(backend.verify_claims({"email": "a@example.org", "email_verified": "true"}))

        with self.settings(OIDC_REQUIRE_VERIFIED_EMAIL=False):
            self.assertTrue(backend.verify_claims({"email": "a@example.org"}))

    def test_verify_claims_required_group(self):
        backend = OIDCBackend()
        with self.settings(OIDC_REQUIRED_GROUP="bugsink"):
            self.assertFalse(backend.verify_claims({"email": "a@example.org", "email_verified": True}))
            self.assertFalse(backend.verify_claims(
                {"email": "a@example.org", "email_verified": True, "groups": ["other"]}))
            self.assertTrue(backend.verify_claims(
                {"email": "a@example.org", "email_verified": True, "groups": ["other", "bugsink"]}))

    def test_create_user_uses_email_as_username_without_password(self):
        user = OIDCBackend().create_user({"email": "a@example.org", "given_name": "Ada"})

        self.assertEqual(("a@example.org", "a@example.org", "Ada"), (user.username, user.email, user.first_name))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.is_active)

    def test_no_user_creation_in_single_user_mode(self):
        with override_settings(SINGLE_USER=True):
            self.assertIsNone(OIDCBackend().create_user({"email": "a@example.org"}))
        self.assertFalse(User.objects.exists())

    def test_admin_group_syncs_superuser_status(self):
        backend = OIDCBackend()
        user = User.objects.create_user(username="a@example.org", email="a@example.org")

        with self.settings(OIDC_ADMIN_GROUP="admins"):
            backend.update_user(user, {"groups": ["admins"]})
            self.assertTrue(User.objects.get().is_superuser)

            backend.update_user(user, {"groups": []})
            self.assertFalse(User.objects.get().is_superuser)

    def test_pending_invite_is_activated_but_deactivated_user_is_not(self):
        backend = OIDCBackend()
        invited = User.objects.create_user(username="invited@example.org", is_active=False)
        deactivated = User.objects.create_user(username="gone@example.org", password="pw", is_active=False)

        self.assertTrue(backend.update_user(invited, {}).is_active)
        self.assertFalse(backend.update_user(deactivated, {}).is_active)

    def test_explicit_endpoint_wins_over_discovery(self):
        with patch("requests.get", side_effect=FakeIdP({}).get):
            self.assertEqual("https://idp.example.org/token", oidc.oidc_setting("OIDC_OP_TOKEN_ENDPOINT"))
            with self.settings(OIDC_OP_TOKEN_ENDPOINT="https://other.example.org/token"):
                self.assertEqual("https://other.example.org/token", oidc.oidc_setting("OIDC_OP_TOKEN_ENDPOINT"))


class LoginFlowTestCase(OIDCTestCase):
    USERINFO = {"email": "ada@example.org", "email_verified": True, "given_name": "Ada"}

    def test_login_creates_and_logs_in_user(self):
        idp = FakeIdP(self.USERINFO)
        response = self.login_via_idp(idp, next_url="/projects/")

        self.assertEqual("/projects/", response.url)
        user = User.objects.get()
        self.assertEqual("ada@example.org", user.username)
        self.assertEqual(str(user.pk), self.client.session["_auth_user_id"])
        self.assertEqual(get_settings().BASE_URL + "/accounts/oidc/callback/", idp.token_requests[0]["redirect_uri"])
        self.assertIn("code_verifier", idp.token_requests[0])

    def test_login_links_existing_user(self):
        user = User.objects.create_user(username="ada@example.org", email="ada@example.org", password="pw")

        self.login_via_idp(FakeIdP(self.USERINFO))

        self.assertEqual(1, User.objects.count())
        self.assertEqual(str(user.pk), self.client.session["_auth_user_id"])

    def test_token_for_other_audience_is_rejected(self):
        response = self.login_via_idp(FakeIdP(self.USERINFO, audience="some-other-client"))

        self.assertEqual(reverse("login") + "?local=1", response.url)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(User.objects.exists())

    def test_logout_ends_idp_session(self):
        self.login_via_idp(FakeIdP(self.USERINFO))

        response = self.client.post(reverse("logout"))

        self.assertTrue(response.url.startswith(DISCOVERY["end_session_endpoint"] + "?id_token_hint="))
        self.assertNotIn("_auth_user_id", self.client.session)


class PasswordLoginTestCase(OIDCTestCase):
    def test_password_login_works_while_idp_unreachable(self):
        User.objects.create_user(username="ada@example.org", password="correct-horse")

        with patch("requests.get", side_effect=requests.ConnectionError):
            failed = self.client.post(reverse("login"), {"username": "ada@example.org", "password": "wrong"})
            succeeded = self.client.post(reverse("login"), {"username": "ada@example.org", "password": "correct-horse"})

        self.assertEqual(200, failed.status_code)
        self.assertEqual(302, succeeded.status_code)

    def test_signup_logs_in_with_multiple_backends(self):
        with override_settings(USER_REGISTRATION=CB_ANYBODY, USER_REGISTRATION_VERIFY_EMAIL=False):
            response = self.client.post(reverse("signup"), {
                "username": "ada@example.org", "password1": "correct-horse", "password2": "correct-horse"})

        self.assertEqual(302, response.status_code)
        self.assertIn("_auth_user_id", self.client.session)

    def test_oidc_only_redirects_to_idp_except_break_glass(self):
        with self.settings(OIDC_ONLY=True):
            response = self.client.get(reverse("login") + "?next=/projects/")
            self.assertEqual(reverse("oidc_authentication_init") + "?next=%2Fprojects%2F", response.url)

            self.assertEqual(200, self.client.get(reverse("login") + "?local=1").status_code)

    def test_oidc_only_disables_signup_and_password_reset(self):
        with self.settings(OIDC_ONLY=True), override_settings(USER_REGISTRATION=CB_ANYBODY):
            self.assertEqual(404, self.client.get(reverse("signup")).status_code)
            self.assertEqual(reverse("oidc_authentication_init"),
                             self.client.get(reverse("request_reset_password")).url)

    @override_django_settings(OIDC_ENABLED=False)
    def test_oidc_endpoints_are_404_when_disabled(self):
        self.assertEqual(404, self.client.get(reverse("oidc_authentication_init")).status_code)
        self.assertEqual(404, self.client.get(reverse("oidc_authentication_callback")).status_code)
