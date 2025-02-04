import uuid

from django.db import models

from django.conf import settings


class TeamRole(models.IntegerChoices):
    MEMBER = 0
    ADMIN = 1


class TeamVisibility(models.IntegerChoices):
    # PUBLIC = 0  # anyone can see the team and its members  not sure if I want this or always want to require click-in
    JOINABLE = 1  # anyone can join
    DISCOVERABLE = 10  # the team is visible, you can request to join(?), but this needs to be approved
    HIDDEN = 99  # the team is not visible to non-members; you need to be invited


class Team(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255, blank=False, null=False, unique=True)

    visibility = models.IntegerField(
        choices=TeamVisibility.choices, default=TeamVisibility.DISCOVERABLE,
        help_text="Which users can see this team and its issues?")

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

    send_email_alerts = models.BooleanField(default=None, null=True, blank=True)
    role = models.IntegerField(choices=TeamRole.choices, default=TeamRole.MEMBER)
    accepted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} team membership of {self.team}"

    class Meta:
        unique_together = ("team", "user")

    def is_admin(self):
        return self.role == TeamRole.ADMIN
