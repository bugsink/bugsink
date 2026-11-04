import base64
import hashlib
import hmac
from urllib.parse import urlsplit

from django.core import signing

from bugsink.app_settings import get_settings

CLIENT_ID_SALT = "mcpserver.client"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
# RFC 8252 §7.1: a private-use scheme only reaches the app that claimed it on the user's machine (Cursor's callback)
PRIVATE_SCHEMES = {"cursor"}
# Claude's connectors (web, Desktop, mobile); Anthropic asks to allow the announced claude.com variant too
CLAUDE_ORIGINS = {"https://claude.ai", "https://claude.com"}
CLAUDE_CALLBACKS = {origin + "/api/mcp/auth_callback" for origin in CLAUDE_ORIGINS}


def base_url():
    return get_settings().BASE_URL


def resource_url():
    return base_url() + "/mcp"


def pkce_matches(verifier, challenge):
    digest = hashlib.sha256(verifier.encode()).digest()
    return hmac.compare_digest(base64.urlsafe_b64encode(digest).rstrip(b"=").decode(), challenge)


def is_allowed_redirect(uri):
    if uri in CLAUDE_CALLBACKS:
        return True
    try:
        parts = urlsplit(uri)
        hostname = parts.hostname
    except ValueError:  # e.g. an unclosed IPv6 bracket
        return False
    if parts.fragment:
        return False
    if parts.scheme == "http":
        return hostname in LOOPBACK_HOSTS
    return parts.scheme in PRIVATE_SCHEMES


def redirect_matches(registered, presented):
    # RFC 8252 §7.3: loopback redirects may use any port
    if not is_allowed_redirect(presented):
        return False
    a, b = urlsplit(registered), urlsplit(presented)
    return (a.scheme, a.hostname, a.path, a.query) == (b.scheme, b.hostname, b.path, b.query)


def sign_client(name, redirect_uris):
    return signing.dumps({"name": name, "redirect_uris": redirect_uris}, salt=CLIENT_ID_SALT)


def load_client(client_id):
    try:
        return signing.loads(client_id, salt=CLIENT_ID_SALT)
    except signing.BadSignature:
        return None
