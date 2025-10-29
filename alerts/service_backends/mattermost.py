import json
import requests
from string import Template
from django.utils import timezone

from django import forms
from django.template.defaultfilters import truncatechars

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


def default_format_title():
    return "$alert_reason issue"


def default_format_text():
    return "[$issue_title]($issue_url)"


class MattermostConfigForm(forms.Form):
    webhook_url = forms.URLField(required=True)
    channel = forms.CharField(
        required=False,
        help_text='Optional: Override channel (e.g., "town-square" or "@username" for DMs)',
    )
    format_title = forms.CharField(
        required=False,
        max_length=200,
        help_text='Title template using $variable syntax (e.g., "$alert_reason issue"). '
        "Available: $alert_reason, $project, $issue_url, $issue_title, $unmute_reason, "
        "$release, $environment. "
        "Leave empty for default.",
    )
    format_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text='Text template using $variable syntax (e.g., "$project\\n$issue_url"). '
        "Available: $alert_reason, $project, $issue_url, $issue_title, $unmute_reason, "
        "$release, $environment. "
        "Leave empty for default.",
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)

        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")
            self.fields["channel"].initial = config.get("channel", "")
            self.fields["format_title"].initial = config.get(
                "format_title", default_format_title()
            )
            self.fields["format_text"].initial = config.get(
                "format_text", default_format_text()
            )

    def get_config(self):
        config = {
            "webhook_url": self.cleaned_data.get("webhook_url"),
        }
        if self.cleaned_data.get("channel"):
            config["channel"] = self.cleaned_data.get("channel")

        config["format_title"] = (
            self.cleaned_data.get("format_title") or default_format_title()
        )
        config["format_text"] = (
            self.cleaned_data.get("format_text") or default_format_text()
        )

        return config


def _safe_markdown(text):
    # Mattermost uses similar markdown escaping as Slack
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("*", "\\*")
        .replace("_", "\\_")
    )


def _store_failure_info(service_config_id, exception, response=None):
    """Store failure information in the MessagingServiceConfig with immediate_atomic"""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)

            config.last_failure_timestamp = timezone.now()
            config.last_failure_error_type = type(exception).__name__
            config.last_failure_error_message = str(exception)

            # Handle requests-specific errors
            if response is not None:
                config.last_failure_status_code = response.status_code
                config.last_failure_response_text = response.text[
                    :2000
                ]  # Limit response text size

                # Check if response is JSON
                try:
                    json.loads(response.text)
                    config.last_failure_is_json = True
                except (json.JSONDecodeError, ValueError):
                    config.last_failure_is_json = False
            else:
                # Non-HTTP errors
                config.last_failure_status_code = None
                config.last_failure_response_text = None
                config.last_failure_is_json = None

            config.save()
        except MessagingServiceConfig.DoesNotExist:
            # Config was deleted while task was running
            pass


def _store_success_info(service_config_id):
    """Clear failure information on successful operation"""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)
            config.clear_failure_status()
            config.save()
        except MessagingServiceConfig.DoesNotExist:
            # Config was deleted while task was running
            pass


def _send_mattermost_message(
    webhook_url, service_config_id, title, text, color="#36a64f", channel=None
):
    """Send a message to Mattermost using attachments format"""
    data = {
        "text": text[:100],  # Fallback text
        "attachments": [
            {
                "fallback": title,
                "color": color,
                "title": title,
                "text": text,
            }
        ],
    }

    if channel:
        data["channel"] = channel

    try:
        result = requests.post(
            webhook_url,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
            timeout=5,
        )

        result.raise_for_status()

        _store_success_info(service_config_id)
    except requests.RequestException as e:
        response = getattr(e, "response", None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


@shared_task
def mattermost_backend_send_test_message(
    webhook_url, project_name, display_name, service_config_id, channel=None
):
    title = "TEST issue"
    text = (
        f"Test message by Bugsink to test the webhook setup.\n\n"
        f"**project**: {_safe_markdown(project_name)}\n"
        f"**name**: {_safe_markdown(display_name)}"
    )

    _send_mattermost_message(webhook_url, service_config_id, title, text, channel)


@shared_task
def mattermost_backend_send_alert(
    webhook_url,
    issue_id,
    state_description,
    alert_article,
    alert_reason,
    service_config_id,
    channel=None,
    unmute_reason=None,
    format_title=None,
    format_text=None,
):
    issue = Issue.objects.get(id=issue_id)

    issue_url = get_settings().BASE_URL + issue.get_absolute_url()
    link_text = _safe_markdown(truncatechars(issue.title(), 200))

    latest_event = issue.event_set.order_by("-digest_order").first()
    release = latest_event.release if latest_event else ""
    environment = latest_event.environment if latest_event else ""

    template_context = {
        "alert_reason": alert_reason,
        "project": _safe_markdown(issue.project.name),
        "issue_url": issue_url,
        "issue_title": link_text,
        "unmute_reason": unmute_reason or "",
        "release": _safe_markdown(release),
        "environment": _safe_markdown(environment),
    }

    title = Template(format_title).safe_substitute(template_context)
    text = Template(format_text).safe_substitute(template_context)
    color = "#ff0000" if alert_reason == "NEW" else "#ff9900"

    _send_mattermost_message(
        webhook_url, service_config_id, title, text, color, channel
    )


class MattermostBackend:
    def __init__(self, service_config):
        self.service_config = service_config

    def get_form_class(self):
        return MattermostConfigForm

    def send_test_message(self):
        config = json.loads(self.service_config.config)
        mattermost_backend_send_test_message.delay(
            config["webhook_url"],
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
            channel=config.get("channel"),
        )

    def send_alert(
        self, issue_id, state_description, alert_article, alert_reason, **kwargs
    ):
        config = json.loads(self.service_config.config)
        mattermost_backend_send_alert.delay(
            config["webhook_url"],
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            channel=config.get("channel"),
            format_title=config.get("format_title", default_format_title()),
            format_text=config.get("format_text", default_format_text()),
            **kwargs,
        )
