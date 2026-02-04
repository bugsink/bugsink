"""
Bugsink Messaging Backend: Microsoft Teams
===========================================

Sends alerts to Microsoft Teams channels via Webhooks.
Uses Adaptive Cards for rich formatting with direct links to issues.

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
import requests

from django import forms
from django.utils import timezone

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


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
    title_color = forms.ChoiceField(
        label="Title Color",
        help_text="Color for the alert title in Teams",
        choices=[
            ("attention", "Red (Attention) - for errors"),
            ("warning", "Yellow (Warning)"),
            ("good", "Green (Good)"),
            ("accent", "Blue (Accent)"),
            ("default", "Default"),
        ],
        initial="attention",
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")
            self.fields["channel_name"].initial = config.get("channel_name", "")
            self.fields["mention_users"].initial = ",".join(config.get("mention_users", []))
            self.fields["title_color"].initial = config.get("title_color", "attention")

    def get_config(self):
        return {
            "webhook_url": self.cleaned_data["webhook_url"],
            "channel_name": self.cleaned_data.get("channel_name", ""),
            "mention_users": [u.strip() for u in self.cleaned_data.get("mention_users", "").split(",") if u.strip()],
            "title_color": self.cleaned_data.get("title_color", "attention"),
        }


def _store_failure_info(service_config_id, exception, response=None):
    """Store failure information in the MessagingServiceConfig."""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)

            config.last_failure_timestamp = timezone.now()
            config.last_failure_error_type = type(exception).__name__
            config.last_failure_error_message = str(exception)

            if response is not None:
                config.last_failure_status_code = response.status_code
                config.last_failure_response_text = response.text[:2000]

                try:
                    json.loads(response.text)
                    config.last_failure_is_json = True
                except (json.JSONDecodeError, ValueError):
                    config.last_failure_is_json = False
            else:
                config.last_failure_status_code = None
                config.last_failure_response_text = None
                config.last_failure_is_json = None

            config.save()
        except MessagingServiceConfig.DoesNotExist:
            pass


def _store_success_info(service_config_id):
    """Clear failure information on successful operation."""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)
            config.clear_failure_status()
            config.save()
        except MessagingServiceConfig.DoesNotExist:
            pass


def _build_adaptive_card(title, facts, title_color, issue_url=None, mention_users=None):
    """Build a Microsoft Teams Adaptive Card payload.

    Args:
        title: The card title text
        facts: List of (key, value) tuples for the fact set
        title_color: Adaptive Card color keyword (attention, warning, good, accent, default)
        issue_url: Optional URL for the "View Issue" button
        mention_users: Optional list of user emails to mention
    """
    fact_items = [{"title": k, "value": v} for k, v in facts]

    # Map lowercase config value to Adaptive Card color (capitalize first letter)
    color_map = {
        "attention": "Attention",
        "warning": "Warning",
        "good": "Good",
        "accent": "Accent",
        "default": "Default",
    }
    card_color = color_map.get(title_color, "Attention")

    body = [
        {
            "type": "TextBlock",
            "size": "Large",
            "weight": "Bolder",
            "text": title,
            "wrap": True,
            "color": card_color
        },
        {
            "type": "FactSet",
            "facts": fact_items
        }
    ]

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


@shared_task
def microsoft_teams_send_test_message(webhook_url, channel_name, mention_users, title_color,
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
        title_color=title_color,
        mention_users=mention_users if mention_users else None
    )

    try:
        result = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        result.raise_for_status()
        _store_success_info(service_config_id)

    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


@shared_task
def microsoft_teams_send_alert(webhook_url, channel_name, mention_users, title_color,
                                issue_id, state_description, alert_article, alert_reason,
                                service_config_id, unmute_reason=None):
    """Send an alert to Microsoft Teams."""
    issue = Issue.objects.get(id=issue_id)
    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    title = f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}"

    facts = [
        ("Error Type", issue.calculated_type or "Unknown"),
        ("Message", (issue.calculated_value or "No message")[:200]),
        ("Project", issue.project.name),
        ("First Seen", issue.first_seen.strftime("%Y-%m-%d %H:%M") if issue.first_seen else "Unknown"),
        ("Last Seen", issue.last_seen.strftime("%Y-%m-%d %H:%M") if issue.last_seen else "Unknown"),
        ("Event Count", str(issue.digested_event_count)),
        ("Alert Type", state_description),
        ("Reason", alert_reason),
    ]

    if unmute_reason:
        facts.append(("Unmute Reason", unmute_reason))

    payload = _build_adaptive_card(
        title=title,
        facts=facts,
        title_color=title_color,
        issue_url=issue_url,
        mention_users=mention_users if mention_users else None
    )

    try:
        result = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        result.raise_for_status()
        _store_success_info(service_config_id)

    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


class MicrosoftTeamsBackend:
    """Backend class for Microsoft Teams integration."""

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return MicrosoftTeamsConfigForm

    def _get_title_color(self, config):
        """Get title_color from config."""
        return config.get("title_color", "attention")

    def send_test_message(self):
        config = json.loads(self.service_config.config)
        microsoft_teams_send_test_message.delay(
            config["webhook_url"],
            config.get("channel_name", ""),
            config.get("mention_users", []),
            self._get_title_color(config),
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)

        microsoft_teams_send_alert.delay(
            config["webhook_url"],
            config.get("channel_name", ""),
            config.get("mention_users", []),
            self._get_title_color(config),
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            **kwargs,
        )
