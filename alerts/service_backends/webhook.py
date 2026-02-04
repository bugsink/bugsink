"""
Bugsink Messaging Backend: Generic Webhook
==========================================

Sends alerts to any HTTP endpoint as JSON payloads.
Flexible for custom integrations, home automation, or third-party services.

Compatible with Bugsink v2.

Installation:
    Copy to: /app/alerts/service_backends/webhook.py
    Register in: /app/alerts/models.py

Requirements:
    - HTTP(S) endpoint that accepts POST requests with JSON body
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

# HTTP Method choices
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
        help_text="Additional headers as JSON, e.g., {\"X-Custom\": \"value\"}",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": '{"X-Custom-Header": "value"}'}),
        required=False,
    )
    include_full_payload = forms.BooleanField(
        label="Include Full Payload",
        help_text="Include all available issue details in the webhook payload",
        initial=True,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        """Initialize form with existing config if provided."""
        config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")
            self.fields["http_method"].initial = config.get("http_method", "POST")
            self.fields["secret_header"].initial = config.get("secret_header", "")
            self.fields["secret_value"].initial = config.get("secret_value", "")
            self.fields["custom_headers"].initial = json.dumps(config.get("custom_headers", {})) if config.get("custom_headers") else ""
            self.fields["include_full_payload"].initial = config.get("include_full_payload", True)

    def clean_custom_headers(self):
        """Validate custom headers as valid JSON."""
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
        """Return configuration as dictionary for storage."""
        return {
            "webhook_url": self.cleaned_data["webhook_url"],
            "http_method": self.cleaned_data["http_method"],
            "secret_header": self.cleaned_data.get("secret_header", ""),
            "secret_value": self.cleaned_data.get("secret_value", ""),
            "custom_headers": self.cleaned_data.get("custom_headers", {}),
            "include_full_payload": self.cleaned_data.get("include_full_payload", True),
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


def _send_webhook(url: str, method: str, payload: dict, secret_header: str = None,
                  secret_value: str = None, custom_headers: dict = None) -> str:
    """Send payload to webhook endpoint."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Bugsink-Webhook/1.0",
    }

    # Add secret header if configured
    if secret_header and secret_value:
        headers[secret_header] = secret_value

    # Add custom headers
    if custom_headers:
        headers.update(custom_headers)

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method=method
    )

    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _build_payload(event_type: str, data: dict, include_full: bool = True) -> dict:
    """Build a standardized webhook payload."""
    payload = {
        "event_type": event_type,
        "timestamp": timezone.now().isoformat(),
        "source": "bugsink",
    }

    if include_full:
        payload["data"] = data
    else:
        # Minimal payload
        payload["summary"] = data.get("summary", "")
        payload["issue_id"] = data.get("issue_id")

    return payload


@shared_task
def webhook_send_test_message(webhook_url, http_method, secret_header, secret_value,
                               custom_headers, include_full_payload,
                               project_name, display_name, service_config_id):
    """Send a test webhook to verify configuration."""

    payload = _build_payload(
        event_type="test",
        data={
            "summary": f"Test webhook from Bugsink - {project_name}",
            "project": project_name,
            "service": display_name or "Webhook",
            "message": "This is a test webhook. Configuration is working correctly.",
            "test": True,
        },
        include_full=include_full_payload,
    )

    try:
        _send_webhook(
            url=webhook_url,
            method=http_method,
            payload=payload,
            secret_header=secret_header,
            secret_value=secret_value,
            custom_headers=custom_headers,
        )
        _store_success_info(service_config_id)
        logger.info(f"Webhook test sent successfully to {webhook_url}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"Webhook error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"Webhook connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending webhook: {e}")
        _store_failure_info(service_config_id, e)


@shared_task
def webhook_send_alert(webhook_url, http_method, secret_header, secret_value,
                        custom_headers, include_full_payload,
                        issue_id, state_description, alert_article, alert_reason,
                        service_config_id, bugsink_base_url=None, unmute_reason=None):
    """Send an alert webhook."""
    from issues.models import Issue

    try:
        issue = Issue.objects.select_related("project").get(pk=issue_id)

        # Build issue URL using same path as Slack backend
        issue_url = None
        if bugsink_base_url:
            issue_url = f"{bugsink_base_url.rstrip('/')}/issues/issue/{issue_id}/event/last/"

        data = {
            "issue_id": str(issue_id),
            "issue_url": issue_url,
            "summary": f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}",
            "error_type": issue.calculated_type or "Unknown",
            "error_message": issue.calculated_value or "No message",
            "project": issue.project.name if issue.project else "Unknown",
            "first_seen": issue.first_seen.isoformat() if issue.first_seen else None,
            "last_seen": issue.last_seen.isoformat() if issue.last_seen else None,
            "event_count": issue.digested_event_count,
            "alert_type": state_description,
            "alert_reason": alert_reason,
        }

        if unmute_reason:
            data["unmute_reason"] = unmute_reason

    except Issue.DoesNotExist:
        issue_url = None
        if bugsink_base_url:
            issue_url = f"{bugsink_base_url.rstrip('/')}/issues/issue/{issue_id}/event/last/"
        data = {
            "issue_id": str(issue_id),
            "issue_url": issue_url,
            "summary": f"[{state_description}] Issue {issue_id}",
            "alert_type": state_description,
            "alert_reason": alert_reason,
        }

    payload = _build_payload(
        event_type="alert",
        data=data,
        include_full=include_full_payload,
    )

    try:
        _send_webhook(
            url=webhook_url,
            method=http_method,
            payload=payload,
            secret_header=secret_header,
            secret_value=secret_value,
            custom_headers=custom_headers,
        )
        _store_success_info(service_config_id)
        logger.info(f"Webhook alert sent for issue {issue_id}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"Webhook error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"Webhook connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending webhook: {e}")
        _store_failure_info(service_config_id, e)


class WebhookBackend:
    """Backend class for Generic Webhook integration.

    Compatible with Bugsink v2 backend interface.
    """

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        """Return the configuration form class."""
        return WebhookConfigForm

    def send_test_message(self):
        """Dispatch test message task."""
        config = json.loads(self.service_config.config)
        webhook_send_test_message.delay(
            config["webhook_url"],
            config.get("http_method", "POST"),
            config.get("secret_header", ""),
            config.get("secret_value", ""),
            config.get("custom_headers", {}),
            config.get("include_full_payload", True),
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

        webhook_send_alert.delay(
            config["webhook_url"],
            config.get("http_method", "POST"),
            config.get("secret_header", ""),
            config.get("secret_value", ""),
            config.get("custom_headers", {}),
            config.get("include_full_payload", True),
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            bugsink_base_url=bugsink_base_url,
            **kwargs,
        )
