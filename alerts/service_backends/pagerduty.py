"""
Bugsink Messaging Backend: PagerDuty
====================================

Creates incidents in PagerDuty for on-call alerting and incident management.

Compatible with Bugsink v2.

Installation:
    Copy to: /app/alerts/service_backends/pagerduty.py
    Register in: /app/alerts/models.py

Requirements:
    - PagerDuty account with Events API v2 access
    - Integration Key (Routing Key) from a PagerDuty service
    - Create at: Service > Integrations > Add Integration > Events API v2
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

# PagerDuty Events API v2 endpoint
PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

# Severity mapping
SEVERITY_CHOICES = [
    ("critical", "Critical"),
    ("error", "Error"),
    ("warning", "Warning"),
    ("info", "Info"),
]


class PagerDutyConfigForm(forms.Form):
    """Configuration form for PagerDuty integration."""

    routing_key = forms.CharField(
        label="Integration/Routing Key",
        help_text="PagerDuty Events API v2 Integration Key (32 characters)",
        max_length=32,
        min_length=32,
        widget=forms.PasswordInput(render_value=True),
    )
    default_severity = forms.ChoiceField(
        label="Default Severity",
        help_text="Severity level for new incidents",
        choices=SEVERITY_CHOICES,
        initial="error",
    )
    service_name = forms.CharField(
        label="Service Name (optional)",
        help_text="Custom source name, defaults to 'Bugsink'",
        max_length=100,
        initial="Bugsink",
        required=False,
    )
    include_link = forms.BooleanField(
        label="Include Issue Link",
        help_text="Add a link to the Bugsink issue in the incident",
        initial=True,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        """Initialize form with existing config if provided."""
        config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)
        if config:
            self.fields["routing_key"].initial = config.get("routing_key", "")
            self.fields["default_severity"].initial = config.get("default_severity", "error")
            self.fields["service_name"].initial = config.get("service_name", "Bugsink")
            self.fields["include_link"].initial = config.get("include_link", True)

    def get_config(self):
        """Return configuration as dictionary for storage."""
        return {
            "routing_key": self.cleaned_data["routing_key"],
            "default_severity": self.cleaned_data["default_severity"],
            "service_name": self.cleaned_data.get("service_name", "Bugsink") or "Bugsink",
            "include_link": self.cleaned_data.get("include_link", True),
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


def _send_pagerduty_event(routing_key: str, payload: dict) -> dict:
    """Send event to PagerDuty Events API v2."""
    payload["routing_key"] = routing_key

    headers = {
        "Content-Type": "application/json",
    }

    request = Request(
        PAGERDUTY_EVENTS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_trigger_payload(summary: str, severity: str, source: str,
                            custom_details: dict = None, dedup_key: str = None,
                            links: list = None) -> dict:
    """Build a PagerDuty Events API v2 trigger payload."""
    payload = {
        "event_action": "trigger",
        "payload": {
            "summary": summary[:1024],  # PagerDuty limit
            "severity": severity,
            "source": source,
            "custom_details": custom_details or {},
        }
    }

    if dedup_key:
        payload["dedup_key"] = dedup_key

    if links:
        payload["links"] = links

    return payload


@shared_task
def pagerduty_send_test_message(routing_key, default_severity, service_name, include_link,
                                 project_name, display_name, service_config_id):
    """Send a test event to verify PagerDuty configuration."""

    payload = _build_trigger_payload(
        summary=f"[Bugsink Test] Configuration verified for {project_name}",
        severity="info",  # Use info for test to avoid unnecessary alerts
        source=service_name,
        custom_details={
            "project": project_name,
            "service": display_name or "PagerDuty",
            "test": True,
            "message": "This is a test event from Bugsink. You can resolve this incident.",
        },
        dedup_key=f"bugsink-test-{service_config_id}",
    )

    try:
        result = _send_pagerduty_event(routing_key, payload)
        _store_success_info(service_config_id)
        logger.info(f"PagerDuty test event sent: {result.get('dedup_key')}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"PagerDuty API error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"PagerDuty connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending to PagerDuty: {e}")
        _store_failure_info(service_config_id, e)


@shared_task
def pagerduty_send_alert(routing_key, default_severity, service_name, include_link,
                          issue_id, state_description, alert_article, alert_reason,
                          service_config_id, bugsink_base_url=None, unmute_reason=None):
    """Create a PagerDuty incident for a Bugsink alert."""
    from issues.models import Issue

    try:
        issue = Issue.objects.select_related("project").get(pk=issue_id)

        summary = f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}"

        custom_details = {
            "error_type": issue.calculated_type or "Unknown",
            "error_message": issue.calculated_value or "No message",
            "project": issue.project.name if issue.project else "Unknown",
            "first_seen": issue.first_seen.isoformat() if issue.first_seen else "Unknown",
            "last_seen": issue.last_seen.isoformat() if issue.last_seen else "Unknown",
            "event_count": issue.digested_event_count,
            "alert_type": state_description,
            "alert_reason": alert_reason,
        }

        if unmute_reason:
            custom_details["unmute_reason"] = unmute_reason

        # Build links if base URL is provided and enabled (use same path as Slack backend)
        links = []
        if include_link and bugsink_base_url:
            links.append({
                "href": f"{bugsink_base_url.rstrip('/')}/issues/issue/{issue_id}/event/last/",
                "text": "View in Bugsink"
            })

        # Use issue fingerprint as dedup key to group related events
        dedup_key = f"bugsink-{issue_id}"

    except Issue.DoesNotExist:
        summary = f"[{state_description}] Issue {issue_id}"
        custom_details = {
            "issue_id": str(issue_id),
            "alert_type": state_description,
            "alert_reason": alert_reason,
        }
        links = []
        dedup_key = f"bugsink-{issue_id}"

    payload = _build_trigger_payload(
        summary=summary,
        severity=default_severity,
        source=service_name,
        custom_details=custom_details,
        dedup_key=dedup_key,
        links=links if links else None,
    )

    try:
        result = _send_pagerduty_event(routing_key, payload)
        _store_success_info(service_config_id)
        logger.info(f"PagerDuty incident created for issue {issue_id}: {result.get('dedup_key')}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"PagerDuty API error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"PagerDuty connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending to PagerDuty: {e}")
        _store_failure_info(service_config_id, e)


class PagerDutyBackend:
    """Backend class for PagerDuty integration.

    Compatible with Bugsink v2 backend interface.
    """

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        """Return the configuration form class."""
        return PagerDutyConfigForm

    def send_test_message(self):
        """Dispatch test message task."""
        config = json.loads(self.service_config.config)
        pagerduty_send_test_message.delay(
            config["routing_key"],
            config.get("default_severity", "error"),
            config.get("service_name", "Bugsink"),
            config.get("include_link", True),
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

        pagerduty_send_alert.delay(
            config["routing_key"],
            config.get("default_severity", "error"),
            config.get("service_name", "Bugsink"),
            config.get("include_link", True),
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            bugsink_base_url=bugsink_base_url,
            **kwargs,
        )
