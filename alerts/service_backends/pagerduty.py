"""
Bugsink Messaging Backend: PagerDuty
====================================

Creates incidents in PagerDuty for on-call alerting and incident management.

Requirements:
    - PagerDuty account with Events API v2 access
    - Integration Key (Routing Key) from a PagerDuty service

Setup:
    1. Go to your PagerDuty service
    2. Navigate to: Integrations > Add Integration
    3. Select "Events API v2"
    4. Copy the 32-character Integration Key (Routing Key)
"""

import json
import requests

from django import forms
from django.utils import timezone

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

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
    include_link = forms.ChoiceField(
        label="Include Issue Link",
        help_text="Add a link to the Bugsink issue in the incident",
        choices=[
            ("yes", "Yes - Include link to Bugsink"),
            ("no", "No - Don't include link"),
        ],
        initial="yes",
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)
        if config:
            self.fields["routing_key"].initial = config.get("routing_key", "")
            self.fields["default_severity"].initial = config.get("default_severity", "error")
            self.fields["service_name"].initial = config.get("service_name", "Bugsink")
            # Support both old boolean and new choice format
            include_link = config.get("include_link", True)
            if isinstance(include_link, bool):
                self.fields["include_link"].initial = "yes" if include_link else "no"
            else:
                self.fields["include_link"].initial = include_link

    def get_config(self):
        return {
            "routing_key": self.cleaned_data["routing_key"],
            "default_severity": self.cleaned_data["default_severity"],
            "service_name": self.cleaned_data.get("service_name", "Bugsink") or "Bugsink",
            "include_link": self.cleaned_data.get("include_link", "yes"),
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
def pagerduty_send_test_message(routing_key, default_severity, service_name, include_link,
                                 project_name, display_name, service_config_id):
    """Send a test event to verify PagerDuty configuration."""
    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"bugsink-test-{service_config_id}",
        "payload": {
            "summary": f"[Bugsink Test] Configuration verified for {project_name}"[:1024],
            "severity": "info",
            "source": service_name,
            "custom_details": {
                "project": project_name,
                "service": display_name or "PagerDuty",
                "test": True,
                "message": "This is a test event from Bugsink. You can resolve this incident.",
            },
        }
    }

    try:
        result = requests.post(
            PAGERDUTY_EVENTS_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
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
def pagerduty_send_alert(routing_key, default_severity, service_name, include_link,
                          issue_id, state_description, alert_article, alert_reason,
                          service_config_id, unmute_reason=None):
    """Create a PagerDuty incident for a Bugsink alert."""
    issue = Issue.objects.get(id=issue_id)
    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    summary = f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}"

    custom_details = {
        "error_type": issue.calculated_type or "Unknown",
        "error_message": issue.calculated_value or "No message",
        "project": issue.project.name,
        "first_seen": issue.first_seen.isoformat() if issue.first_seen else "Unknown",
        "last_seen": issue.last_seen.isoformat() if issue.last_seen else "Unknown",
        "event_count": issue.digested_event_count,
        "alert_type": state_description,
        "alert_reason": alert_reason,
    }

    if unmute_reason:
        custom_details["unmute_reason"] = unmute_reason

    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"bugsink-{issue_id}",
        "payload": {
            "summary": summary[:1024],
            "severity": default_severity,
            "source": service_name,
            "custom_details": custom_details,
        }
    }

    # Support both old boolean and new string format
    should_include_link = include_link if isinstance(include_link, bool) else (include_link == "yes")
    if should_include_link:
        payload["links"] = [{"href": issue_url, "text": "View in Bugsink"}]

    try:
        result = requests.post(
            PAGERDUTY_EVENTS_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        result.raise_for_status()
        _store_success_info(service_config_id)

    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


class PagerDutyBackend:
    """Backend class for PagerDuty integration."""

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return PagerDutyConfigForm

    def send_test_message(self):
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
        config = json.loads(self.service_config.config)

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
            **kwargs,
        )
