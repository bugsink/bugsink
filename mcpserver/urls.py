from django.urls import path

from . import mcp_views, oauth_views

urlpatterns = [
    path(".well-known/oauth-protected-resource", oauth_views.protected_resource_metadata),
    path(".well-known/oauth-protected-resource/mcp", oauth_views.protected_resource_metadata),
    path(".well-known/oauth-authorization-server", oauth_views.authorization_server_metadata),
    path("oauth/register", oauth_views.register, name="oauth_register"),
    path("oauth/authorize", oauth_views.authorize, name="oauth_authorize"),
    path("oauth/token", oauth_views.token, name="oauth_token"),
    # both forms: a POST to /mcp would otherwise hit APPEND_SLASH
    path("mcp", mcp_views.mcp, name="mcp"),
    path("mcp/", mcp_views.mcp),
    path("oauth/connections/", oauth_views.connections, name="oauth_connections"),
]
