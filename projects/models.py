import uuid
import json
from datetime import datetime, timezone

from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from django.template.defaultfilters import date
from django.utils.timezone import localtime

from bugsink.app_settings import get_settings
from bugsink.transaction import delay_on_commit

from compat.dsn import build_dsn

from teams.models import TeamMembership

from .tasks import delete_project_deps


# ## Visibility/Access-design
#
# Some more "philosophical/architectural" thoughts on visibility and access across projects and teams. As bullets:
#
# * The primary way to organize issues is the _project_
# * A Team models a group of people that work together on related projects.
# * A Team membership implies: Project-membership is available (a "Join" button is shown, no further approval needed)
# * Project-membership must be explicitly opted into.
#       This is "as it stands", i.e. that's how it currently works; I'm not committed to that approach though. Reasons
#       in favor of this approach:
#       * explicit over implicit
#       * forces a choice about notification settings on the user.
#       * allows users to self-organise their workflow: not everyone on every team cares about every project.
#       against / possible changes
#       * yet another action needed
#       * possible change: allow access to the project without clicking "join", but keep it in a separate tab (workflow)
#
# * visibility of teams does not affect visibility of associated projects
# * user.is_superuser can see/do everything
#
# Some open ends/ choices to be made:
#
# * team admin role: should it be inherited on the project level? My sense is "yes", and this is implemented in
#     `_check_project_admin` but not in the templates.
# * team admins currently have the ability to see projects, diverging from the "explicitly opted into" rule. Makes some
#       sense, but could be an argument for the general "allow access" option mentioned above.
# * if there are very many generally visible teams/projects, some more means of organisation may be needed (search?).
#       a first step towards that is probably: navigate by-team (we currently just have a "team projects" tab.
#       "icebox" though, because at that scale we'll first have to deal with other questions of scale.


class ProjectRole(models.IntegerChoices):
    MEMBER = 0, _("Member")
    ADMIN = 1, _("Admin")


class ProjectVisibility(models.IntegerChoices):
    # PUBLIC = 0  # anyone can see the project and its members; not sure if I want this or always require click-in
    JOINABLE = 1, _("Joinable")  # anyone can join

    # the project's existance is visible, but the project itself is not. the idea would be that you can "request to
    # join" (which is currently not implemented as a button, but you could do it 'out of bands' i.e. via email or chat).
    DISCOVERABLE = 10, _("Discoverable")

    # the project's exsitance is only visible to team-members; you still need to explicitly click "join" which will
    # immediately make you a member
    TEAM_MEMBERS = 99, _("Team Members")

    # having projects that are part of a certain team, but not visible to the team members, was considered, but
    # rejected. The basic thinking on the rejection is: it would hollow out the concept of Team to the point of
    # meaninglessness. If you want "secret" projects, you can just create a hidden team (possibly even with just a
    # single member) and add the project to that.
    # HIDDEN


class Project(models.Model):
    # id is implied which makes it an Integer; we would prefer a uuid but the sentry clients have int baked into the DSN
    # parser (we could also introduce a special field for that purpose but that's ugly too)

    team = models.ForeignKey("teams.Team", blank=False, null=True, on_delete=models.SET_NULL)

    name = models.CharField(pgettext_lazy("Project", "Name"), max_length=255, blank=False, null=False, unique=True)
    slug = models.SlugField(max_length=50, blank=False, null=False, unique=True)
    is_deleted = models.BooleanField(default=False)

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
        _("Visibility"), choices=ProjectVisibility.choices, default=ProjectVisibility.TEAM_MEMBERS,
        help_text=_("Which users can see this project and its issues?"))

    # ingestion/digestion quota
    quota_exceeded_until = models.DateTimeField(null=True, blank=True)
    quota_exceeded_reason = models.CharField(max_length=255, null=False, default="null")
    next_quota_check = models.PositiveIntegerField(null=False, default=0)

    # retention
    retention_max_event_count = models.PositiveIntegerField(_("Retention max event count"), default=10_000)

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

    def get_retention_max_event_count(self):
        # apply global maximum if set (allows for meaningfully decreasing max retention after the fact). (note that
        # down-adjusting the cross-project max will not automatically affect per-project; implementing that would
        # require some kind of fractional/relative adjustment which seems more complex than it's worth).
        if get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT is not None:
            return min(self.retention_max_event_count, get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT)
        return self.retention_max_event_count

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

    def delete_deferred(self):
        """Marks the project as deleted, and schedules deletion of all related objects"""
        self.is_deleted = True
        self.save(update_fields=["is_deleted"])

        delay_on_commit(delete_project_deps, str(self.id))

    def is_joinable(self, user=None):
        if user is not None:
            # take the user's team membership into account
            try:
                TeamMembership.objects.get(team=self.team, user=user)
                return True
            except TeamMembership.DoesNotExist:
                pass

        return self.visibility <= ProjectVisibility.JOINABLE

    def is_discoverable(self):
        return self.visibility <= ProjectVisibility.DISCOVERABLE

    def get_warnings(self):
        now = datetime.now(timezone.utc)
        from ingest.views import BaseIngestAPIView
        if BaseIngestAPIView.is_quota_still_exceeded(self, now):
            period_name, nr_of_periods, gte_threshold = json.loads(self.quota_exceeded_reason)
            # TODO i18n
            per_fmt = "%s %ss" % (nr_of_periods, period_name) if nr_of_periods != 1 else period_name
            date_fmt = date(localtime(self.quota_exceeded_until), "j M G:i T")
            return ["Event ingestion stopped until %s. Reason: project quota (%s events per %s) exceeded." % (
                      date_fmt, gte_threshold, per_fmt)]

        return []

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
        ]


class ProjectMembership(models.Model):
    project = models.ForeignKey(Project, on_delete=models.DO_NOTHING)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    send_email_alerts = models.BooleanField(_("Send email alerts"), default=None, null=True)

    role = models.IntegerField(_("Role"), choices=ProjectRole.choices, default=ProjectRole.MEMBER)
    accepted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} project membership of {self.project}"

    class Meta:
        unique_together = ("project", "user")

    def is_admin(self):
        return self.role == ProjectRole.ADMIN
