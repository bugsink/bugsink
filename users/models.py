import secrets

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils.translation import gettext_lazy as _, get_language_info

from bugsink.transaction import immediate_atomic


def language_choices():
    items = [("auto", _("Auto (browser preference)"))]

    for code, _label in settings.LANGUAGES:
        info = get_language_info(code)
        label = info["name_local"] \
            if info["name_local"] == info["name_translated"] \
            else f"{info['name_local']} ({info['name_translated']})"
        items.append((code, label))
    return items


class User(AbstractUser):
    # > If you’re starting a new project, it’s highly recommended to set up a custom user model, even if the default
    # > User model is sufficient for you. This model behaves identically to the default user model, but you’ll be able
    # > to customize it in the future if the need arises

    # (The above is no longer the only reason for a custom User model, since we started introducing custom fields.
    # Regarding those fields, there is some pressure in the docs to put UserProfile fields in a separate model, but
    # as long as the number of fields is small I think the User model makes more sense. We can always push them out
    # later)

    # Inactive users may complete email/setup unless an administrator has deactivated them.
    is_deactivated = models.BooleanField(default=False)

    send_email_alerts = models.BooleanField(default=True, blank=True)

    THEME_CHOICES = [
        ("system", _("System Default")),
        ("light", _("Light")),
        ("dark", _("Dark")),
    ]
    theme_preference = models.CharField(
        max_length=10,
        choices=THEME_CHOICES,
        default="system",
        blank=False,
    )
    language = models.CharField(
        _("Language"),
        max_length=10,
        choices=language_choices,
        default="auto",
        blank=False,
    )

    class Meta:
        db_table = 'auth_user'

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        password_changed = (
            self.pk is not None and self._password is not None
            and (update_fields is None or "password" in update_fields))
        email_may_change = self.pk is not None and (update_fields is None or "email" in update_fields)
        if not password_changed and not email_may_change:
            return super().save(*args, **kwargs)

        using = kwargs.get("using") or self._state.db
        with immediate_atomic(using=using, only_if_needed=True):
            saved_user = type(self).objects.using(using).filter(pk=self.pk)
            invalidate_tokens = password_changed or (
                email_may_change and saved_user.exclude(email=self.email).exists())
            super().save(*args, **kwargs)
            if invalidate_tokens:
                self.emailverification_set.all().delete()

    def deactivate(self):
        self.is_active = False
        self.is_deactivated = True
        self.is_superuser = False
        self.is_staff = False
        self.set_unusable_password()  # also invalidates existing sessions
        self.save()

        self.teammembership_set.all().delete()
        self.projectmembership_set.all().delete()
        self.emailverification_set.all().delete()
        self.auth_tokens.filter(is_user_bound=True).delete()


class EmailVerification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    email = models.EmailField()
    token = models.CharField(max_length=64, default=secrets.token_urlsafe, blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} ({self.email})"
