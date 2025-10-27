from django.db import models
from projects.models import Project

from .service_backends.slack import SlackBackend
from .service_backends.mattermost import MattermostBackend


def kind_choices():
    # no 18n needed for no
    return [
        ("slack", "Slack"),
        ("mattermost", "Mattermost"),
    ]


class MessagingServiceConfig(models.Model):
    project = models.ForeignKey(Project, on_delete=models.DO_NOTHING, related_name="service_configs")
    display_name = models.CharField(max_length=100, blank=False,
                                    help_text='For display in the UI, e.g. "#general on company Slack"')

    kind = models.CharField(choices=kind_choices, max_length=20, default="slack")

    config = models.TextField(blank=False)

    # Alert backend failure tracking
    last_failure_timestamp = models.DateTimeField(null=True, blank=True,
                                                  help_text="When the last failure occurred")
    last_failure_status_code = models.IntegerField(null=True, blank=True,
                                                   help_text="HTTP status code of the failed request")
    last_failure_response_text = models.TextField(null=True, blank=True,
                                                  help_text="Response text from the failed request")
    last_failure_is_json = models.BooleanField(null=True, blank=True,
                                               help_text="Whether the response was valid JSON")
    last_failure_error_type = models.CharField(max_length=100, null=True, blank=True,
                                               help_text="Type of error that occurred (e.g., 'requests.HTTPError')")
    last_failure_error_message = models.TextField(null=True, blank=True,
                                                  help_text="Error message from the exception")

    def get_backend(self):
        if self.kind == "slack":
            return SlackBackend(self)
        elif self.kind == "mattermost":
            return MattermostBackend(self)
        else:
            raise ValueError(f"Unknown backend kind: {self.kind}")

    def clear_failure_status(self):
        """Clear all failure tracking fields on successful operation"""
        self.last_failure_timestamp = None
        self.last_failure_status_code = None
        self.last_failure_response_text = None
        self.last_failure_is_json = None
        self.last_failure_error_type = None
        self.last_failure_error_message = None

    def has_recent_failure(self):
        """Check if this config has a recent failure"""
        return self.last_failure_timestamp is not None
