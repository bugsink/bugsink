import uuid

from django.db import models

from django.conf import settings
from django.utils.translation import gettext_lazy as _, pgettext_lazy

from bugsink.app_settings import CB_ADMINS, CB_ANYBODY, CB_MEMBERS, get_settings


class TeamRole(models.IntegerChoices):
    MEMBER = 0, _("Member")
    ADMIN = 1, _("Admin")


class TeamVisibility(models.IntegerChoices):
    # PUBLIC = 0  # anyone can see the team and its members  not sure if I want this or always want to require click-in
    JOINABLE = 1, _("Joinable")  # anyone can join

    # the team's existance is visible in lists, but there is no "Join" button. the idea would be that you can "request
    # to join" (which is currently not implemented as a button, but you could do it 'out of bands' i.e. via email or
    # chat).
    DISCOVERABLE = 10, _("Discoverable")

    # the team is not visible to non-members; you need to be invited
    HIDDEN = 99, _("Hidden")


class Team(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(pgettext_lazy("Team", "Name"), max_length=255, blank=False, null=False, unique=True)

    visibility = models.IntegerField(
        _("Visibility"),
        choices=TeamVisibility.choices, default=TeamVisibility.DISCOVERABLE,
        help_text=_("Which users can see this team and its issues?"))

    def __str__(self):
        return self.name

    def is_joinable(self):
        return self.visibility <= TeamVisibility.JOINABLE

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
        ]


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    send_email_alerts = models.BooleanField(_("Send email alerts"), default=None, null=True, blank=True)
    role = models.IntegerField(_("Role"), choices=TeamRole.choices, default=TeamRole.MEMBER)
    accepted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} team membership of {self.team}"

    class Meta:
        unique_together = ("team", "user")

    def is_admin(self):
        return self.role == TeamRole.ADMIN


def teams_visible_to_user(queryset, user):
    if user.is_superuser:
        return queryset
    return queryset.filter(
        models.Q(teammembership__user=user) | models.Q(visibility__lt=TeamVisibility.HIDDEN)
    ).distinct()


def user_is_team_admin(user, team):
    return (
        user.is_superuser
        or TeamMembership.objects.filter(
            team=team,
            user=user,
            role=TeamRole.ADMIN,
            accepted=True,
        ).exists()
    )


def user_can_create_team(user):
    team_creation = get_settings().TEAM_CREATION
    return (
        team_creation in (CB_ANYBODY, CB_MEMBERS)
        or (user.is_superuser and team_creation == CB_ADMINS)
    )
