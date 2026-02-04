"""
Bugsink Messaging Backend: Generic Webhook
==========================================

Sends alerts to any HTTP endpoint as JSON payloads.
Flexible for custom integrations, home automation, or third-party services.

Requirements:
    - HTTP(S) endpoint that accepts POST requests with JSON body
"""

import json
import requests

from django import forms
from django.utils import timezone

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


HTTP_METHOD_CHOICES = [
    ("POST", "POST"),
    ("PUT", "PUT"),
    ("PATCH", "PATCH"),
]


class WebhookConfigForm(forms.Form):
    """Configuration form for Generic Webhook integration."""

    webhook_url = forms.URLField(
        label="Webhook URL",
        help_text="HTTP(S) endpoint to send alerts to",
        widget=forms.URLInput(attrs={"placeholder": "https://example.com/webhook"}),
    )
    http_method = forms.ChoiceField(
        label="HTTP Method",
        help_text="HTTP method for the request",
        choices=HTTP_METHOD_CHOICES,
        initial="POST",
    )
    secret_header = forms.CharField(
        label="Secret Header Name (optional)",
        help_text="Header name for authentication, e.g., 'X-Webhook-Secret'",
        max_length=100,
        required=False,
    )
    secret_value = forms.CharField(
        label="Secret Value (optional)",
        help_text="Value for the secret header",
        widget=forms.PasswordInput(render_value=True),
        required=False,
    )
    custom_headers = forms.CharField(
        label="Custom Headers (optional)",
        help_text='Additional headers as JSON, e.g., {"X-Custom": "value"}',
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": '{"X-Custom-Header": "value"}'}),
        required=False,
    )
    payload_type = forms.ChoiceField(
        label="Payload Type",
        help_text="How much data to include in the webhook",
        choices=[
            ("full", "Full payload (all issue details)"),
            ("minimal", "Minimal payload (summary + issue ID only)"),
        ],
        initial="full",
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")
            self.fields["http_method"].initial = config.get("http_method", "POST")
            self.fields["secret_header"].initial = config.get("secret_header", "")
            self.fields["secret_value"].initial = config.get("secret_value", "")
            custom_hdrs = config.get("custom_headers", {})
            self.fields["custom_headers"].initial = json.dumps(custom_hdrs) if custom_hdrs else ""
            # Support both old boolean and new choice format
            if "payload_type" in config:
                self.fields["payload_type"].initial = config.get("payload_type", "full")
            else:
                include_full = config.get("include_full_payload", True)
                self.fields["payload_type"].initial = "full" if include_full else "minimal"

    def clean_custom_headers(self):
        value = self.cleaned_data.get("custom_headers", "").strip()
        if not value:
            return {}
        try:
            headers = json.loads(value)
            if not isinstance(headers, dict):
                raise forms.ValidationError("Custom headers must be a JSON object")
            return headers
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f"Invalid JSON: {e}")

    def get_config(self):
        return {
            "webhook_url": self.cleaned_data["webhook_url"],
            "http_method": self.cleaned_data["http_method"],
            "secret_header": self.cleaned_data.get("secret_header", ""),
            "secret_value": self.cleaned_data.get("secret_value", ""),
            "custom_headers": self.cleaned_data.get("custom_headers", {}),
            "payload_type": self.cleaned_data.get("payload_type", "full"),
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


@shared_task
def webhook_send_test_message(webhook_url, http_method, secret_header, secret_value,
                               custom_headers, include_full_payload,
                               project_name, display_name, service_config_id):
    """Send a test webhook to verify configuration."""
    payload = {
        "event_type": "test",
        "timestamp": timezone.now().isoformat(),
        "source": "bugsink",
    }

    if include_full_payload:
        payload["data"] = {
            "summary": f"Test webhook from Bugsink - {project_name}",
            "project": project_name,
            "service": display_name or "Webhook",
            "message": "This is a test webhook. Configuration is working correctly.",
            "test": True,
        }
    else:
        payload["summary"] = f"Test webhook from Bugsink - {project_name}"

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Bugsink-Webhook/1.0",
    }

    if secret_header and secret_value:
        headers[secret_header] = secret_value

    if custom_headers:
        headers.update(custom_headers)

    try:
        result = requests.request(
            http_method,
            webhook_url,
            data=json.dumps(payload),
            headers=headers,
            timeout=30,
        )
        result.raise_for_status()
        _store_success_info(service_config_id)

    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


@shared_task
def webhook_send_alert(webhook_url, http_method, secret_header, secret_value,
                        custom_headers, include_full_payload,
                        issue_id, state_description, alert_article, alert_reason,
                        service_config_id, unmute_reason=None):
    """Send an alert webhook."""
    issue = Issue.objects.get(id=issue_id)
    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    payload = {
        "event_type": "alert",
        "timestamp": timezone.now().isoformat(),
        "source": "bugsink",
    }

    data = {
        "issue_id": str(issue_id),
        "issue_url": issue_url,
        "summary": f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}",
        "error_type": issue.calculated_type or "Unknown",
        "error_message": issue.calculated_value or "No message",
        "project": issue.project.name,
        "first_seen": issue.first_seen.isoformat() if issue.first_seen else None,
        "last_seen": issue.last_seen.isoformat() if issue.last_seen else None,
        "event_count": issue.digested_event_count,
        "alert_type": state_description,
        "alert_reason": alert_reason,
    }

    if unmute_reason:
        data["unmute_reason"] = unmute_reason

    if include_full_payload:
        payload["data"] = data
    else:
        payload["summary"] = data["summary"]
        payload["issue_id"] = data["issue_id"]

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Bugsink-Webhook/1.0",
    }

    if secret_header and secret_value:
        headers[secret_header] = secret_value

    if custom_headers:
        headers.update(custom_headers)

    try:
        result = requests.request(
            http_method,
            webhook_url,
            data=json.dumps(payload),
            headers=headers,
            timeout=30,
        )
        result.raise_for_status()
        _store_success_info(service_config_id)

    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


class WebhookBackend:
    """Backend class for Generic Webhook integration."""

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return WebhookConfigForm

    def _get_include_full_payload(self, config):
        """Convert payload_type to boolean for backwards compatibility."""
        if "payload_type" in config:
            return config["payload_type"] == "full"
        return config.get("include_full_payload", True)

    def send_test_message(self):
        config = json.loads(self.service_config.config)
        webhook_send_test_message.delay(
            config["webhook_url"],
            config.get("http_method", "POST"),
            config.get("secret_header", ""),
            config.get("secret_value", ""),
            config.get("custom_headers", {}),
            self._get_include_full_payload(config),
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)

        webhook_send_alert.delay(
            config["webhook_url"],
            config.get("http_method", "POST"),
            config.get("secret_header", ""),
            config.get("secret_value", ""),
            config.get("custom_headers", {}),
            self._get_include_full_payload(config),
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            **kwargs,
        )
