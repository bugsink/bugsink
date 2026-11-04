from django.test import SimpleTestCase

from mcpserver.oauth import is_allowed_redirect, load_client, pkce_matches, redirect_matches, sign_client

RFC7636_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC7636_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class PkceTests(SimpleTestCase):
    def test_rfc7636_vector(self):
        self.assertTrue(pkce_matches(RFC7636_VERIFIER, RFC7636_CHALLENGE))

    def test_wrong_verifier(self):
        self.assertFalse(pkce_matches("not-the-verifier", RFC7636_CHALLENGE))


class RedirectTests(SimpleTestCase):
    def test_allowed(self):
        for uri in ["http://localhost:1234/cb", "http://127.0.0.1/cb", "http://[::1]:5/cb",
                    "cursor://anysphere.cursor-mcp/oauth/callback"]:
            self.assertTrue(is_allowed_redirect(uri), uri)

    def test_rejected(self):
        for uri in ["https://evil.com/cb", "http://localhost.evil.com/cb", "https://localhost/cb",
                    "http://localhost/cb#fragment", "http://[::1/cb", "https://vscode.dev/redirect",
                    "javascript:alert(1)", "vscode://some/callback", "https://claude.ai/api/mcp/other",
                    "https://claude.ai.evil.com/api/mcp/auth_callback", "http://claude.ai/api/mcp/auth_callback"]:
            self.assertFalse(is_allowed_redirect(uri), uri)

    def test_claude_connector_callbacks_allowed(self):
        for uri in ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"]:
            self.assertTrue(is_allowed_redirect(uri), uri)
            self.assertTrue(redirect_matches(uri, uri), uri)

    def test_port_is_ignored_path_and_scheme_are_not(self):
        self.assertTrue(redirect_matches("http://localhost:1234/cb", "http://localhost:5555/cb"))
        self.assertFalse(redirect_matches("http://localhost:1234/cb", "http://localhost:1234/other"))
        self.assertFalse(redirect_matches("http://localhost:1234/cb", "https://evil.com/cb"))
        self.assertTrue(redirect_matches(
            "cursor://anysphere.cursor-mcp/oauth/callback", "cursor://anysphere.cursor-mcp/oauth/callback"))
        self.assertFalse(redirect_matches("cursor://localhost/cb", "http://localhost/cb"))


class ClientIdTests(SimpleTestCase):
    def test_round_trip(self):
        client_id = sign_client("Claude Code", ["http://localhost:1234/cb"])
        self.assertEqual(load_client(client_id), {"name": "Claude Code", "redirect_uris": ["http://localhost:1234/cb"]})

    def test_tampered(self):
        client_id = sign_client("Claude Code", ["http://localhost:1234/cb"])
        tampered = client_id[:-1] + ("A" if client_id[-1] != "A" else "B")
        self.assertIsNone(load_client(tampered))
