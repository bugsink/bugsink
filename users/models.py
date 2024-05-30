import secrets

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings


class User(AbstractUser):
    # > If you’re starting a new project, it’s highly recommended to set up a custom user model, even if the default
    # > User model is sufficient for you. This model behaves identically to the default user model, but you’ll be able
    # > to customize it in the future if the need arises

    class Meta:
        db_table = 'auth_user'


class EmailVerification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    email = models.EmailField()  # redundant, but future-proof for when we allow multiple emails per user
    token = models.CharField(max_length=64, default=secrets.token_urlsafe, blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} ({self.email})"
