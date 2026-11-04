import json

from django.test import Client, TestCase

from bugsink.app_settings import get_settings
from mcpserver.oauth import load_client


class DiscoveryTests(TestCase):
    def test_protected_resource_metadata(self):
        base = get_settings().BASE_URL
        for path in ["/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.json(), {"resource": base + "/mcp", "authorization_servers": [base]})

    def test_authorization_server_metadata(self):
        base = get_settings().BASE_URL
        metadata = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(metadata["issuer"], base)
        self.assertEqual(metadata["token_endpoint"], base + "/oauth/token")
        self.assertEqual(metadata["registration_endpoint"], base + "/oauth/register")
        self.assertEqual(metadata["code_challenge_methods_supported"], ["S256"])


class RegisterTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def register(self, body):
        return self.client.post("/oauth/register", body, content_type="application/json")

    def test_registers_loopback_client(self):
        response = self.register(json.dumps(
            {"client_name": "Claude Code", "redirect_uris": ["http://localhost:1234/callback"]}))
        self.assertEqual(response.status_code, 201)
        client = load_client(response.json()["client_id"])
        self.assertEqual(client, {"name": "Claude Code", "redirect_uris": ["http://localhost:1234/callback"]})

    def test_drops_web_redirects_vscode_also_registers(self):
        response = self.register(json.dumps({"client_name": "Visual Studio Code", "redirect_uris": [
            "https://insiders.vscode.dev/redirect", "https://vscode.dev/redirect",
            "http://127.0.0.1/", "http://127.0.0.1:33418/"]}))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["redirect_uris"], ["http://127.0.0.1/", "http://127.0.0.1:33418/"])
        self.assertEqual(load_client(response.json()["client_id"])["redirect_uris"],
                         ["http://127.0.0.1/", "http://127.0.0.1:33418/"])

    def test_rejects_non_loopback_redirect(self):
        response = self.register(json.dumps({"redirect_uris": ["https://evil.com/callback"]}))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_redirect_uri"})

    def test_rejects_non_json(self):
        response = self.register("not json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_client_metadata"})
