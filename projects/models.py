import uuid

from django.db import models
from django.conf import settings
from django.utils.text import slugify

from bugsink.app_settings import get_settings

from compat.dsn import build_dsn

from teams.models import TeamMembership, TeamRole


class ProjectRole(models.IntegerChoices):
    MEMBER = 0
    ADMIN = 1


class ProjectVisibility(models.IntegerChoices):
    # PUBLIC = 0  # anyone can see the project and its members; not sure if I want this or always require click-in
    JOINABLE = 1  # anyone can join
    DISCOVERABLE = 10  # the project's existance is visible, you can request to join(?), but this needs to be approved
    TEAM_MEMBERS = 99  # the project is only visible to team-members (and for some(?) things they need to click "join")


class Project(models.Model):
    # id is implied which makes it an Integer; we would prefer a uuid but the sentry clients have int baked into the DSN
    # parser (we could also introduce a special field for that purpose but that's ugly too)

    team = models.ForeignKey("teams.Team", blank=False, null=True, on_delete=models.SET_NULL)

    name = models.CharField(max_length=255, blank=False, null=False, unique=True)
    slug = models.SlugField(max_length=50, blank=False, null=False, unique=True)

    # sentry_key mirrors the "public" part of the sentry DSN. As of late 2023 Sentry's docs say the this about DSNs:
    #
    # > DSNs are safe to keep public because they only allow submission of new events and related event data; they do
    # > not allow read access to any information.
    #
    # The "because" in that sentence is dubious at least; however, I get why they say it, because they want to do JS and
    # native apps too, and there's really no way to do those without exposing (some) endpoint. Anyway, I don't think the
    # "public" key is public, and if you can help it it's always better to keep it private.
    sentry_key = models.UUIDField(editable=False, default=uuid.uuid4)

    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, through="ProjectMembership")

    # We don't implement private_key because as of late 2023 the Sentry documentation says the following:
    # > The secret part of the DSN is optional and effectively deprecated. While clients will still honor it, if
    # > supplied, future versions of Sentry will entirely ignore it.
    # private_key = ...

    # denormalized/cached/counted fields below
    has_releases = models.BooleanField(editable=False, default=False)
    digested_event_count = models.PositiveIntegerField(null=False, blank=False, default=0, editable=False)
    stored_event_count = models.IntegerField(blank=False, null=False, default=0, editable=False)

    # alerting conditions
    alert_on_new_issue = models.BooleanField(default=True)
    alert_on_regression = models.BooleanField(default=True)
    alert_on_unmute = models.BooleanField(default=True)

    # visibility
    visibility = models.IntegerField(
        choices=ProjectVisibility.choices, default=ProjectVisibility.TEAM_MEMBERS,
        help_text="Which users can see this project and its issues?")

    # ingestion/digestion quota
    quota_exceeded_until = models.DateTimeField(null=True, blank=True)
    next_quota_check = models.PositiveIntegerField(null=False, default=0)

    # retention
    retention_max_event_count = models.PositiveIntegerField(default=10_000)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return f"/issues/{ self.id }/"

    @property
    def dsn(self):
        return build_dsn(str(get_settings().BASE_URL), self.id, self.sentry_key.hex)

    def get_latest_release(self):
        from releases.models import ordered_releases
        if not hasattr(self, "_latest_release"):  # per-instance cache
            self._latest_release = list(ordered_releases(project=self))[-1]
        return self._latest_release

    def save(self, *args, **kwargs):
        if self.slug in [None, ""]:
            # we don't want to have empty slugs, so we'll generate a unique one
            base_slug = slugify(self.name)
            similar_slugs = Project.objects.filter(slug__startswith=base_slug).values_list("slug", flat=True)
            self.slug = base_slug
            i = 0
            while self.slug in similar_slugs:
                self.slug = f"{base_slug}-{i}"
                i += 1

        super().save(*args, **kwargs)

    def is_joinable(self, user=None):
        if user is not None:
            # take the user's team membership into account
            try:
                tm = TeamMembership.objects.get(team=self.team, user=user)
                if tm.role == TeamRole.ADMIN:
                    return True
            except TeamMembership.DoesNotExist:
                pass

        return self.visibility <= ProjectVisibility.JOINABLE

    def is_discoverable(self):
        return self.visibility <= ProjectVisibility.DISCOVERABLE

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
        ]


class ProjectMembership(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    send_email_alerts = models.BooleanField(default=None, null=True)

    role = models.IntegerField(choices=ProjectRole.choices, default=ProjectRole.MEMBER)
    accepted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} project membership of {self.project}"

    class Meta:
        unique_together = ("project", "user")

    def is_admin(self):
        return self.role == ProjectRole.ADMIN
