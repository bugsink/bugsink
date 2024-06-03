import uuid

from django.db import models

from django.conf import settings


class TeamRole(models.IntegerChoices):
    MEMBER = 0
    ADMIN = 1


class TeamVisibility(models.IntegerChoices):
    PUBLIC = 0  # anyone can join(?); or even just click-through(?)
    VISIBLE = 1  # the team is visible, you can request to join(?), but this needs to be approved
    HIDDEN = 2  # the team is not visible to non-members; you need to be invited


class Team(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255, blank=False, null=False)
    slug = models.SlugField(max_length=50, blank=False, null=False)

    visibility = models.IntegerField(choices=TeamVisibility.choices, default=TeamVisibility.PUBLIC)

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    # send_email_alerts = models.BooleanField(default=True)  TODO (see also Project)
    role = models.IntegerField(choices=TeamRole.choices, default=TeamRole.MEMBER)
    accepted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} team membership of {self.team}"

    class Meta:
        unique_together = ("team", "user")
