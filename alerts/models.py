from django.db import models
from projects.models import Project

from .service_backends.slack import SlackBackend


class MessagingServiceConfig(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="service_configs")
    display_name = models.CharField(max_length=100, blank=False,
                                    help_text='For display in the UI, e.g. "#general on company Slack"')

    kind = models.CharField(choices=[("slack", "Slack (or compatible)"), ], max_length=20, default="slack")

    config = models.TextField(blank=False)

    def get_backend(self):
        # once we have multiple backends: lookup by kind.
        return SlackBackend(self)
