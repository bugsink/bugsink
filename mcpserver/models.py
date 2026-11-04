import secrets

from django.conf import settings
from django.db import models


def new_secret():
    return secrets.token_urlsafe(32)


class OAuthAuthorizationCode(models.Model):
    code = models.CharField(max_length=64, unique=True, default=new_secret)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    client_id = models.TextField()
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=128)
    description = models.CharField(max_length=255)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE)
    capabilities = models.JSONField()
    expires_at = models.DateTimeField()


class OAuthGrant(models.Model):
    auth_token = models.OneToOneField("bsmain.AuthToken", on_delete=models.CASCADE, related_name="oauth_grant")
    client_id = models.TextField()
    client_name = models.CharField(max_length=200)
    refresh_token = models.CharField(max_length=64, unique=True, default=new_secret)
    refresh_expires_at = models.DateTimeField()
    previous_refresh_token = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    previous_valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)


class McpToolCall(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    client_name = models.CharField(max_length=255)
    tool = models.CharField(max_length=100)
    arguments = models.JSONField()
    error = models.TextField(blank=True)  # empty means the call succeeded
