import secrets

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings


class User(AbstractUser):
    # > If you’re starting a new project, it’s highly recommended to set up a custom user model, even if the default
    # > User model is sufficient for you. This model behaves identically to the default user model, but you’ll be able
    # > to customize it in the future if the need arises

    # (The above is no longer the only reason for a custom User model, since we started introducing custom fields.
    # Regarding those fields, there is some pressure in the docs to put UserProfile fields in a separate model, but
    # as long as the number of fields is small I think the User model makes more sense. We can always push them out
    # later)

    send_email_alerts = models.BooleanField(default=True, blank=True)

    class Meta:
        db_table = 'auth_user'


class EmailVerification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    email = models.EmailField()  # redundant, but future-proof for when we allow multiple emails per user
    token = models.CharField(max_length=64, default=secrets.token_urlsafe, blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} ({self.email})"
