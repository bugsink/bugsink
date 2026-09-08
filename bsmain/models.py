import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone

from bugsink.api_capabilities import CAPABILITY_FIELD_NAMES, INSTALLATION_ONLY_CAPABILITIES


UNNAMED_TOKEN_DESCRIPTION = "Unnamed token"


def generate_token():
    # nchars = nbytes * 2
    return secrets.token_hex(nbytes=20)


class AuthToken(models.Model):
    token = models.CharField(max_length=40, unique=True, default=generate_token, validators=[
        RegexValidator(regex=r'^[a-f0-9]{40}$', message='Token must be a 40-character hexadecimal string.'),
    ])
    description = models.CharField(max_length=255, default=UNNAMED_TOKEN_DESCRIPTION)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    is_user_bound = models.BooleanField(default=False)
    is_project_bound = models.BooleanField(default=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="auth_tokens",
    )
    project = models.ForeignKey(
        "projects.Project",
        blank=True,
        null=True,
        on_delete=models.DO_NOTHING,
        related_name="auth_tokens",
    )
    expires_at = models.DateTimeField(blank=True, null=True, editable=False)

    issues_read = models.BooleanField(default=False)
    events_read = models.BooleanField(default=False)
    issues_comment = models.BooleanField(default=False)
    issues_triage = models.BooleanField(default=False)
    issues_delete = models.BooleanField(default=False)
    releases_read = models.BooleanField(default=False)
    releases_create = models.BooleanField(default=False)
    debug_files_upload = models.BooleanField(default=False)
    projects_read = models.BooleanField(default=False)
    projects_manage = models.BooleanField(default=False)
    teams_read = models.BooleanField(default=False)
    teams_manage = models.BooleanField(default=False)

    @classmethod
    def create_full_access(cls, **kwargs):
        kwargs.update({
            "is_user_bound": False,
            "is_project_bound": False,
            "user": None,
            "project": None,
            **{field_name: True for field_name in CAPABILITY_FIELD_NAMES.values()},
        })
        return cls.objects.create(**kwargs)

    @property
    def capabilities(self):
        # Return a set of capabilities that this token has, based on the boolean fields.
        return {
            capability
            for capability, field_name in CAPABILITY_FIELD_NAMES.items()
            if getattr(self, field_name)
        }

    def clean(self):
        # Currently used exclusively by get_token_for_authentication(). A future DRF token serializer must call it
        # explicitly; neither save() nor ModelSerializer does so automatically. The granular token UI must likewise
        # validate with this method, directly or through ModelForm. The checks below cover many cases that are unlikely
        # to occur in practice, but hey this is a security-sensitive model so we might as well write down our
        # assumptions very explicitly, so that we can be sure that only valid tokens.
        errors = {}
        is_expired = self.expires_at is not None and self.expires_at <= timezone.now()

        if not self.is_user_bound and self.user_id is not None:
            errors["user"] = "Service tokens cannot have a user."
        elif self.is_user_bound and not is_expired:
            if self.user_id is None:
                errors["user"] = "Active user-bound tokens require a user."
            elif not self.user.is_active:
                errors["user"] = "Active user-bound tokens require an active user."

        if not self.is_project_bound and self.project_id is not None:
            errors["project"] = "Installation tokens cannot have a project."
        elif self.is_project_bound and not is_expired:
            if self.project_id is None:
                errors["project"] = "Active project-bound tokens require a project."
            elif self.project.is_deleted:
                errors["project"] = "Active project-bound tokens require a non-deleted project."

        forbidden_capabilities = self.capabilities & INSTALLATION_ONLY_CAPABILITIES
        if self.is_project_bound and forbidden_capabilities:
            errors["is_project_bound"] = "Project-bound tokens cannot have capabilities: %s." % ", ".join(
                sorted(forbidden_capabilities)
            )

        if errors:
            raise ValidationError(errors)

    def revoke(self):
        now = timezone.now()
        if self.expires_at is None or self.expires_at > now:
            self.expires_at = now
            self.save(update_fields=("expires_at",))

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
