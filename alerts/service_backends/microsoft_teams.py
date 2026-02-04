"""
Bugsink Messaging Backend: Microsoft Teams
===========================================

Sends alerts to Microsoft Teams channels via Webhooks.
Uses Adaptive Cards for rich formatting with direct links to issues.

Compatible with Bugsink v2.

Installation:
    Copy to: /app/alerts/service_backends/microsoft_teams.py
    Register in: /app/alerts/models.py

Requirements:
    - Microsoft Teams Webhook URL (one of the following methods):

    Method 1 - Workflows (Recommended, new):
        1. Open Teams channel > "..." menu > "Workflows"
        2. Search for "Post to a channel when a webhook request is received"
        3. Configure the workflow and copy the webhook URL
        URL format: https://xxx.webhook.office.com/webhookb2/...

    Method 2 - Legacy Incoming Webhook (deprecated, retiring 2026):
        1. Channel Settings > Connectors > Incoming Webhook
        URL format: https://outlook.office.com/webhook/...

Note: Both URL formats are supported. Microsoft is retiring legacy
Office 365 Connectors by March 2026 - migrate to Workflows.
"""

import json
import logging
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from django import forms
from django.utils import timezone

from snappea.decorators import shared_task
from bugsink.transaction import immediate_atomic

logger = logging.getLogger(__name__)


class MicrosoftTeamsConfigForm(forms.Form):
    """Configuration form for Microsoft Teams integration."""

    webhook_url = forms.URLField(
        label="Webhook URL",
        help_text="Microsoft Teams Webhook URL (from Workflows or legacy Incoming Webhook)",
        widget=forms.URLInput(attrs={"placeholder": "https://xxx.webhook.office.com/..."}),
    )
    channel_name = forms.CharField(
        label="Channel Name (optional)",
        help_text="Display name for reference, e.g., '#alerts'",
        max_length=100,
        required=False,
    )
    mention_users = forms.CharField(
        label="Mention Users (optional)",
        help_text="Comma-separated user emails to mention, e.g., 'user@company.com'",
        required=False,
    )
    theme_color = forms.CharField(
        label="Theme Color",
        help_text="Hex color for the card accent (without #)",
        max_length=6,
        initial="d63333",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        """Initialize form with existing config if provided."""
        config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")
            self.fields["channel_name"].initial = config.get("channel_name", "")
            self.fields["mention_users"].initial = ",".join(config.get("mention_users", []))
            self.fields["theme_color"].initial = config.get("theme_color", "d63333")

    def get_config(self):
        """Return configuration as dictionary for storage."""
        return {
            "webhook_url": self.cleaned_data["webhook_url"],
            "channel_name": self.cleaned_data.get("channel_name", ""),
            "mention_users": [u.strip() for u in self.cleaned_data.get("mention_users", "").split(",") if u.strip()],
            "theme_color": self.cleaned_data.get("theme_color", "d63333"),
        }


def _store_failure_info(service_config_id, exception, response=None):
    """Store failure info in MessagingServiceConfig using individual fields."""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)
            config.last_failure_timestamp = timezone.now()
            config.last_failure_error_type = type(exception).__name__
            config.last_failure_error_message = str(exception)[:2000]

            if response is not None:
                if hasattr(response, 'status'):
                    config.last_failure_status_code = response.status
                elif hasattr(response, 'code'):
                    config.last_failure_status_code = response.code
                else:
                    config.last_failure_status_code = None

                response_text = getattr(response, 'text', None)
                if response_text:
                    config.last_failure_response_text = response_text[:2000]
                    try:
                        json.loads(response_text)
                        config.last_failure_is_json = True
                    except (json.JSONDecodeError, ValueError):
                        config.last_failure_is_json = False
                else:
                    config.last_failure_response_text = None
                    config.last_failure_is_json = None
            else:
                config.last_failure_status_code = None
                config.last_failure_response_text = None
                config.last_failure_is_json = None

            config.save()
        except MessagingServiceConfig.DoesNotExist:
            logger.warning(f"MessagingServiceConfig {service_config_id} not found for failure tracking")


def _store_success_info(service_config_id):
    """Clear failure info on successful operation."""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)
            config.clear_failure_status()
            config.save()
        except MessagingServiceConfig.DoesNotExist:
            pass


def _build_adaptive_card(title: str, facts: list, theme_color: str, issue_url: str = None, mention_users: list = None):
    """Build a Microsoft Teams Adaptive Card payload."""

    # Build facts for the FactSet
    fact_items = [{"title": k, "value": v} for k, v in facts]

    body = [
        {
            "type": "TextBlock",
            "size": "Large",
            "weight": "Bolder",
            "text": title,
            "wrap": True,
            "color": "Attention"
        },
        {
            "type": "FactSet",
            "facts": fact_items
        }
    ]

    # Add mentions if configured
    if mention_users:
        mention_text = " ".join([f"<at>{email}</at>" for email in mention_users])
        body.append({
            "type": "TextBlock",
            "text": f"CC: {mention_text}",
            "wrap": True,
            "size": "Small"
        })

    actions = []
    if issue_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "View Issue in Bugsink",
            "url": issue_url
        })

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "msteams": {
                        "width": "Full"
                    },
                    "body": body,
                    "actions": actions if actions else None
                }
            }
        ]
    }

    # Add entity mentions for @mentions to work
    if mention_users:
        card["attachments"][0]["content"]["msteams"]["entities"] = [
            {
                "type": "mention",
                "text": f"<at>{email}</at>",
                "mentioned": {
                    "id": email,
                    "name": email
                }
            }
            for email in mention_users
        ]

    return card


def _send_to_teams(webhook_url: str, payload: dict):
    """Send payload to Microsoft Teams webhook."""
    headers = {
        "Content-Type": "application/json",
    }

    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


@shared_task
def microsoft_teams_send_test_message(webhook_url, channel_name, mention_users, theme_color,
                                       project_name, display_name, service_config_id):
    """Send a test message to verify Teams configuration."""

    facts = [
        ("Project", project_name),
        ("Service", display_name or "Microsoft Teams"),
        ("Status", "Configuration verified"),
    ]

    payload = _build_adaptive_card(
        title="Bugsink Test Message",
        facts=facts,
        theme_color=theme_color,
        mention_users=mention_users if mention_users else None
    )

    try:
        _send_to_teams(webhook_url, payload)
        _store_success_info(service_config_id)
        logger.info(f"Teams test message sent successfully to {channel_name or 'webhook'}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"Teams API error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"Teams connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending to Teams: {e}")
        _store_failure_info(service_config_id, e)


@shared_task
def microsoft_teams_send_alert(webhook_url, channel_name, mention_users, theme_color,
                                issue_id, state_description, alert_article, alert_reason,
                                service_config_id, bugsink_base_url=None, unmute_reason=None):
    """Send an alert to Microsoft Teams."""
    from issues.models import Issue

    try:
        issue = Issue.objects.select_related("project").get(pk=issue_id)

        title = f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}"

        facts = [
            ("Error Type", issue.calculated_type or "Unknown"),
            ("Message", (issue.calculated_value or "No message")[:200]),
            ("Project", issue.project.name if issue.project else "Unknown"),
            ("First Seen", issue.first_seen.strftime("%Y-%m-%d %H:%M") if issue.first_seen else "Unknown"),
            ("Last Seen", issue.last_seen.strftime("%Y-%m-%d %H:%M") if issue.last_seen else "Unknown"),
            ("Event Count", str(issue.digested_event_count)),
            ("Alert Type", state_description),
            ("Reason", alert_reason),
        ]

        if unmute_reason:
            facts.append(("Unmute Reason", unmute_reason))

        # Build issue URL using the issue's get_absolute_url method (same as Slack backend)
        issue_url = None
        if bugsink_base_url:
            issue_url = f"{bugsink_base_url.rstrip('/')}/issues/issue/{issue_id}/event/last/"

    except Issue.DoesNotExist:
        title = f"[{state_description}] Issue {issue_id}"
        facts = [
            ("Issue ID", str(issue_id)),
            ("Alert Type", state_description),
            ("Reason", alert_reason),
        ]
        issue_url = None
        if bugsink_base_url:
            issue_url = f"{bugsink_base_url.rstrip('/')}/issues/issue/{issue_id}/event/last/"

    payload = _build_adaptive_card(
        title=title,
        facts=facts,
        theme_color=theme_color,
        issue_url=issue_url,
        mention_users=mention_users if mention_users else None
    )

    try:
        _send_to_teams(webhook_url, payload)
        _store_success_info(service_config_id)
        logger.info(f"Teams alert sent for issue {issue_id}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"Teams API error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"Teams connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending to Teams: {e}")
        _store_failure_info(service_config_id, e)


class MicrosoftTeamsBackend:
    """Backend class for Microsoft Teams integration.

    Compatible with Bugsink v2 backend interface.
    """

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        """Return the configuration form class."""
        return MicrosoftTeamsConfigForm

    def send_test_message(self):
        """Dispatch test message task."""
        config = json.loads(self.service_config.config)
        microsoft_teams_send_test_message.delay(
            config["webhook_url"],
            config.get("channel_name", ""),
            config.get("mention_users", []),
            config.get("theme_color", "d63333"),
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        """Dispatch alert task."""
        from bugsink.app_settings import get_settings
        config = json.loads(self.service_config.config)

        # Get base URL from Bugsink settings (same as Slack backend)
        bugsink_base_url = get_settings().BASE_URL

        microsoft_teams_send_alert.delay(
            config["webhook_url"],
            config.get("channel_name", ""),
            config.get("mention_users", []),
            config.get("theme_color", "d63333"),
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            bugsink_base_url=bugsink_base_url,
            **kwargs,
        )
