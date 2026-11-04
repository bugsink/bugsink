import json
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from bsmain.models import AuthToken, generate_token
from bugsink.api_capabilities import CAPABILITY_FIELD_NAMES
from bugsink.decorators import atomic_for_request_method, login_exempt
from bugsink.transaction import immediate_atomic

from .forms import OAuthConsentForm
from .models import McpToolCall, OAuthAuthorizationCode, OAuthGrant, new_secret
from .oauth import (
    PRIVATE_SCHEMES, base_url, is_allowed_redirect, load_client, pkce_matches, redirect_matches, resource_url,
    sign_client)

CODE_LIFETIME = timedelta(minutes=10)
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)
REFRESH_REPLAY_WINDOW = timedelta(seconds=60)
MCP_REMOTE_VERSION = "0.16.0"


class OAuthRedirect(HttpResponseRedirect):
    # Django refuses to redirect to non-http(s) schemes by default
    allowed_schemes = ["http", "https", *PRIVATE_SCHEMES]


@login_exempt
@require_GET
def protected_resource_metadata(request):
    return JsonResponse({"resource": resource_url(), "authorization_servers": [base_url()]})


@login_exempt
@require_GET
def authorization_server_metadata(request):
    base = base_url()
    return JsonResponse({
        "issuer": base,
        "authorization_endpoint": base + "/oauth/authorize",
        "token_endpoint": base + "/oauth/token",
        "registration_endpoint": base + "/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


@login_exempt
@csrf_exempt
@require_POST
def register(request):
    try:
        metadata = json.loads(request.body)
    except ValueError:
        metadata = None
    if not isinstance(metadata, dict):
        return JsonResponse({"error": "invalid_client_metadata"}, status=400)

    redirect_uris = metadata.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not all(isinstance(uri, str) for uri in redirect_uris):
        return JsonResponse({"error": "invalid_redirect_uri"}, status=400)
    # VS Code and Cursor also register web callbacks (vscode.dev, cursor.com); keep only the local ones
    redirect_uris = [uri for uri in redirect_uris if is_allowed_redirect(uri)]
    if not redirect_uris:
        return JsonResponse({"error": "invalid_redirect_uri"}, status=400)

    name = str(metadata.get("client_name") or "MCP client")[:200]
    return JsonResponse({
        "client_id": sign_client(name, redirect_uris),
        "client_name": name,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",  # nosec B105
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }, status=201)


@atomic_for_request_method
def authorize(request):
    client_id = request.GET.get("client_id", "")
    client = load_client(client_id)
    redirect_uri = request.GET.get("redirect_uri", "")
    if client is None or not any(redirect_matches(uri, redirect_uri) for uri in client["redirect_uris"]):
        return render(request, "mcpserver/oauth_error.html", status=400)

    def back(**params):
        if "state" in request.GET:
            params["state"] = request.GET["state"]
        separator = "&" if "?" in redirect_uri else "?"
        return OAuthRedirect(redirect_uri + separator + urlencode(params))

    if request.GET.get("response_type") != "code":
        return back(error="unsupported_response_type")
    # RFC 7636: an S256 challenge is 43 base64url characters; 128 is the spec's upper bound
    if (not 43 <= len(request.GET.get("code_challenge", "")) <= 128
            or request.GET.get("code_challenge_method") != "S256"):
        return back(error="invalid_request", error_description="PKCE with S256 is required.")
    resource = request.GET.get("resource")
    if resource is not None and resource.rstrip("/") != resource_url():
        return back(error="invalid_target")

    if request.method == "POST" and "deny" in request.POST:
        return back(error="access_denied")

    form = OAuthConsentForm(
        request.POST if request.method == "POST" else None, user=request.user, client_name=client["name"])
    if form.is_valid():
        code = OAuthAuthorizationCode.objects.create(
            user=request.user,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=request.GET["code_challenge"],
            description=form.cleaned_data["description"],
            project=form.cleaned_data["project"],
            capabilities=form.selected_capabilities(),
            expires_at=timezone.now() + CODE_LIFETIME,
        )
        return back(code=code.code)

    return render(request, "mcpserver/consent.html", {
        "form": form, "client_name": client["name"], "action": request.get_full_path()})


def _token_error(error, status=400):
    response = JsonResponse({"error": error}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _token_response(grant, now):
    response = JsonResponse({
        "access_token": grant.auth_token.token,
        "token_type": "Bearer",  # nosec B105
        "expires_in": max(0, int((grant.auth_token.expires_at - now).total_seconds())),
        "refresh_token": grant.refresh_token,
    })
    response["Cache-Control"] = "no-store"
    return response


def _delete_expired(now):
    OAuthAuthorizationCode.objects.filter(expires_at__lte=now).delete()
    AuthToken.objects.filter(oauth_grant__refresh_expires_at__lte=now).delete()  # cascades the grant


def _exchange_code(data, now):
    if not all(data.get(name) for name in ("code", "client_id", "redirect_uri", "code_verifier")):
        return _token_error("invalid_request")
    client = load_client(data["client_id"])
    if client is None:
        return _token_error("invalid_client", status=401)

    code = OAuthAuthorizationCode.objects.filter(code=data["code"], expires_at__gt=now).first()
    if (code is None or code.client_id != data["client_id"] or code.redirect_uri != data["redirect_uri"]
            or not pkce_matches(data["code_verifier"], code.code_challenge)):
        return _token_error("invalid_grant")

    code.delete()
    auth_token = AuthToken.objects.create(
        description=code.description,
        is_user_bound=True,
        user=code.user,
        is_project_bound=code.project_id is not None,
        project=code.project,
        expires_at=now + ACCESS_TOKEN_LIFETIME,
        **{CAPABILITY_FIELD_NAMES[capability]: True for capability in code.capabilities},
    )
    grant = OAuthGrant.objects.create(
        auth_token=auth_token, client_id=code.client_id, client_name=client["name"],
        refresh_expires_at=now + REFRESH_TOKEN_LIFETIME)
    return _token_response(grant, now)


def _refresh(data, now):
    presented = data.get("refresh_token")
    if not presented:
        return _token_error("invalid_request")

    grants = OAuthGrant.objects.select_related("auth_token__user", "auth_token__project")
    # parallel sessions sharing one credential refresh at the same moment; the loser gets the winner's result
    replayed = grants.filter(previous_refresh_token=presented, previous_valid_until__gt=now).first()
    if replayed is not None and data.get("client_id", replayed.client_id) == replayed.client_id:
        return _token_response(replayed, now)

    grant = grants.filter(refresh_token=presented, refresh_expires_at__gt=now).first()
    if grant is None or data.get("client_id", grant.client_id) != grant.client_id:
        return _token_error("invalid_grant")

    auth_token = grant.auth_token
    auth_token.token = generate_token()
    auth_token.expires_at = now + ACCESS_TOKEN_LIFETIME
    try:
        auth_token.clean()
    except ValidationError:
        auth_token.delete()
        return _token_error("invalid_grant")
    auth_token.save(update_fields=["token", "expires_at"])

    grant.previous_refresh_token = grant.refresh_token
    grant.previous_valid_until = now + REFRESH_REPLAY_WINDOW
    grant.refresh_token = new_secret()
    grant.refresh_expires_at = now + REFRESH_TOKEN_LIFETIME
    grant.last_refreshed_at = now
    grant.save()
    return _token_response(grant, now)


@login_exempt
@csrf_exempt
@require_POST
def token(request):
    now = timezone.now()
    with immediate_atomic():
        _delete_expired(now)
        grant_type = request.POST.get("grant_type")
        if grant_type == "authorization_code":
            return _exchange_code(request.POST, now)
        if grant_type == "refresh_token":
            return _refresh(request.POST, now)
        return _token_error("unsupported_grant_type")


@atomic_for_request_method
def connections(request):
    grants = OAuthGrant.objects.select_related("auth_token__user", "auth_token__project")
    if not request.user.is_superuser:
        grants = grants.filter(auth_token__user=request.user)

    if request.method == "POST":
        grant = get_object_or_404(grants, pk=request.POST.get("disconnect"))
        grant.auth_token.delete()  # cascades the grant
        messages.success(request, _("Agent disconnected"))
        return redirect("oauth_connections")

    grants = list(grants.order_by("-created_at"))
    for grant in grants:
        grant.capability_list = sorted(grant.auth_token.capabilities)

    calls = McpToolCall.objects.select_related("user").order_by("-timestamp")
    if not request.user.is_superuser:
        calls = calls.filter(user=request.user)
    calls = list(calls[:100])
    for call in calls:
        call.arguments_text = ", ".join(f"{key}={value}" for key, value in call.arguments.items())

    return render(request, "mcpserver/connections.html", {
        "grants": grants, "calls": calls, "setup_instructions": _setup_instructions(resource_url())})


def _setup_instructions(url):
    def entry(value):
        return json.dumps({"bugsink": value}, indent=2)[2:-2]

    return [
        {"agent": _("Claude (web, Desktop, mobile)"), "where": _(
            "In Claude, go to Settings → Connectors → Add custom connector and enter this URL:"),
         "snippet": url,
         "then": _("Claude signs in through your browser. Bugsink must be reachable from the internet over HTTPS, "
                   "because Claude connects from Anthropic's servers.")},
        {"agent": "Claude Code", "where": _("Run in a terminal:"),
         "snippet": f"claude mcp add --transport http --scope user bugsink {url}",
         "then": _("Then run /mcp in Claude Code and choose Authenticate.")},
        {"agent": "Claude Desktop", "where": _(
            "Quit Claude Desktop first (it overwrites the file while running), then add to \"mcpServers\" in "
            "~/Library/Application Support/Claude/claude_desktop_config.json (requires Node.js):"),
         "snippet": entry({"command": "npx", "args": ["-y", f"mcp-remote@{MCP_REMOTE_VERSION}", url]}),
         "then": _("Start Claude Desktop; the sign-in opens in your browser.")},
        {"agent": "Codex CLI", "where": _("Add to ~/.codex/config.toml:"),
         "snippet": f'[mcp_servers.bugsink]\nurl = "{url}"',
         "then": _("Then run: codex mcp login bugsink")},
        {"agent": "VS Code (Copilot)", "where": _("Run \"MCP: Open User Configuration\" and add to \"servers\":"),
         "snippet": entry({"type": "http", "url": url}),
         "then": _("Start the server in the MCP view; VS Code asks you to sign in.")},
        {"agent": "Cursor", "where": _("Add to \"mcpServers\" in ~/.cursor/mcp.json:"),
         "snippet": entry({"url": url}),
         "then": _("Then click \"Needs login\" next to bugsink in Cursor Settings → MCP.")},
    ]
