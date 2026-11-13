import json
import re
import time
from urllib.parse import urlparse

import requests
from django import forms
from django.template.defaultfilters import truncatechars
from django.utils import timezone

from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic
from issues.models import Issue
from snappea.decorators import shared_task

from .base import BaseWebhookBackend
from .webhook_security import validate_webhook_url

MASKED = "[MASKED]"
ROUTING_KEY_RE = re.compile(r"^[A-Za-z0-9]{32}$")
EVENTS_URLS = {
    "us": "https://events.pagerduty.com/v2/enqueue",
    "eu": "https://events.eu.pagerduty.com/v2/enqueue",
}
RETRY_DELAYS = [1, 2]  # i.e. 3 attempts in total


class PagerDutyConfigForm(forms.Form):
    routing_key = forms.CharField(
        label="Integration key",
        required=True,
        strip=True,
        help_text="Integration Key of an Events API v2 integration on your PagerDuty service",
    )
    region = forms.ChoiceField(
        choices=[("us", "US (events.pagerduty.com)"), ("eu", "EU (events.eu.pagerduty.com)")],
        initial="us",
    )
    severity = forms.ChoiceField(
        choices=[("critical", "Critical"), ("error", "Error"), ("warning", "Warning"), ("info", "Info")],
        initial="error",
        help_text="Severity of the PagerDuty alerts that Bugsink creates",
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)

        super().__init__(*args, **kwargs)
        if config:
            self.fields["routing_key"].initial = config.get("routing_key", "")
            self.fields["region"].initial = config.get("region", "us")
            self.fields["severity"].initial = config.get("severity", "error")

    def get_config(self):
        return {
            "routing_key": self.cleaned_data.get("routing_key"),
            "region": self.cleaned_data.get("region"),
            "severity": self.cleaned_data.get("severity"),
        }

    def clean_routing_key(self):
        routing_key = self.cleaned_data["routing_key"]
        if not ROUTING_KEY_RE.fullmatch(routing_key):
            raise forms.ValidationError("Integration Key must be 32 letters and digits.")
        return routing_key

    def clean_region(self):
        region = self.cleaned_data["region"]
        try:
            validate_webhook_url(EVENTS_URLS[region])
        except ValueError as e:
            raise forms.ValidationError(str(e)) from e
        return region


def _store_failure_info(service_config_id, exception, response=None, routing_key=None):
    """Store failure information in the MessagingServiceConfig with immediate_atomic"""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)

            error_message = str(exception)
            if routing_key:
                error_message = error_message.replace(routing_key, MASKED)

            config.last_failure_timestamp = timezone.now()
            config.last_failure_error_type = type(exception).__name__
            config.last_failure_error_message = error_message

            if response is not None:
                response_text = response.text
                if routing_key:
                    response_text = response_text.replace(routing_key, MASKED)

                config.last_failure_status_code = response.status_code
                config.last_failure_response_text = response_text[:2000]  # Limit response text size

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


def _is_retryable(exception):
    response = getattr(exception, "response", None)
    if response is None:
        return isinstance(exception, (requests.ConnectionError, requests.Timeout))
    return response.status_code == 429 or response.status_code >= 500


def _post_event(service_config_id, routing_key, region, event):
    """Send one event to the PagerDuty Events API v2; returns whether it was accepted."""
    data = json.dumps({"routing_key": routing_key, **event})

    for delay in RETRY_DELAYS + [None]:
        try:
            result = PagerDutyBackend.safe_post(
                EVENTS_URLS[region], data=data, headers={"Content-Type": "application/json"})
            result.raise_for_status()
            _store_success_info(service_config_id)
            return True

        except requests.RequestException as e:
            if delay is None or not _is_retryable(e):
                _store_failure_info(service_config_id, e, getattr(e, "response", None), routing_key)
                return False

        except Exception as e:
            _store_failure_info(service_config_id, e, routing_key=routing_key)
            return False

        time.sleep(delay)


def _source():
    return urlparse(get_settings().BASE_URL).hostname or "bugsink"


@shared_task
def pagerduty_backend_send_test_message(routing_key, region, project_name, display_name, service_config_id):
    _post_event(service_config_id, routing_key, region, {
        "event_action": "trigger",
        "dedup_key": f"bugsink-test-{service_config_id}",
        "client": get_settings().SITE_TITLE,
        "client_url": get_settings().BASE_URL,
        "payload": {
            "summary": f"[{project_name}] TEST issue",
            "source": _source(),
            "severity": "info",
            "component": project_name,
            "custom_details": {
                "message": "Test message by Bugsink to test the PagerDuty setup.",
                "project": project_name,
                "message_backend": display_name,
            },
        },
    })


@shared_task
def pagerduty_backend_send_alert(
        routing_key, region, severity, issue_id, state_description, alert_article, alert_reason, service_config_id,
        unmute_reason=None):

    issue = Issue.objects.get(id=issue_id)
    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    custom_details = {
        "alert_reason": f"{alert_reason} issue",
        "issue": issue.friendly_id(),
        "project": issue.project.name,
        "events": issue.digested_event_count,
        "first_seen": issue.first_seen.isoformat(),
        "last_seen": issue.last_seen.isoformat(),
        "issue_url": issue_url,
    }
    if issue.transaction:
        custom_details["transaction"] = issue.transaction
    if unmute_reason:
        custom_details["unmute_reason"] = unmute_reason

    _post_event(service_config_id, routing_key, region, {
        "event_action": "trigger",
        "dedup_key": issue_id,
        "client": get_settings().SITE_TITLE,
        "client_url": get_settings().BASE_URL,
        "links": [{"href": issue_url, "text": "View on Bugsink"}],
        "payload": {
            "summary": truncatechars(f"[{issue.project.name}] {issue.title()}", 1024),
            "source": _source(),
            "severity": severity,
            "component": issue.project.name,
            "class": issue.calculated_type or "Message",
            "custom_details": custom_details,
        },
    })


@shared_task
def pagerduty_backend_send_resolve(routing_key, region, issue_ids, service_config_id):
    # Issues may be (in the process of being) deleted at this point; the issue id as dedup_key is all we need.
    for issue_id in issue_ids:
        if not _post_event(service_config_id, routing_key, region, {"event_action": "resolve", "dedup_key": issue_id}):
            return  # failure is recorded; the remaining events would most likely fail in the same way


class PagerDutyBackend(BaseWebhookBackend):
    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return PagerDutyConfigForm

    def send_test_message(self):
        config = json.loads(self.service_config.config)
        pagerduty_backend_send_test_message.delay(
            config["routing_key"],
            config["region"],
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)
        pagerduty_backend_send_alert.delay(
            config["routing_key"],
            config["region"],
            config["severity"],
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            **kwargs,
        )

    def send_resolve(self, issue_ids):
        config = json.loads(self.service_config.config)
        pagerduty_backend_send_resolve.delay(config["routing_key"], config["region"], issue_ids, self.service_config.id)
