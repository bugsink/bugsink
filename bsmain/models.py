import secrets

from django.db import models
from django.core.validators import RegexValidator


def generate_token():
    # nchars = nbytes * 2
    return secrets.token_hex(nbytes=20)


class AuthToken(models.Model):
    """Global (Bugsink-wide) token for authentication."""
    token = models.CharField(max_length=40, unique=True, default=generate_token, validators=[
        RegexValidator(regex=r'^[a-f0-9]{40}$', message='Token must be a 40-character hexadecimal string.'),
    ])
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    def __str__(self):
        return f"AuthToken(token={self.token})"


class CachedModelCount(models.Model):
    """Model to cache the count of a specific model."""

    app_label = models.CharField(max_length=255)
    model_name = models.CharField(max_length=255)
    count = models.PositiveIntegerField(null=False, blank=False)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('app_label', 'model_name')
