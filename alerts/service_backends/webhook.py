"""Generic (neutral) outgoing-webhook alert backend.

POSTs JSON (``Content-Type: application/json``) to any URL, so Bugsink alerts
can reach systems without a product-specific backend (e.g. Matrix via
matrix-hookshot, n8n, home-grown receivers).

Without a ``body_template`` a neutral default payload is sent. With one, the
body is rendered via stdlib ``string.Template`` (``safe_substitute``) -- no
logic/eval, minimal attack surface. Every placeholder expands to a JSON-encoded
value, so the rule is: put a bare ``$var`` where a JSON value belongs and the
result is always valid JSON, e.g. ``{"text": $summary, "url": $issue_url}``.

Placeholders: ``$summary``, ``$issue_title``, ``$issue_url``, ``$project``,
``$alert_reason``, ``$issue_id``, ``$issue_friendly_id``, ``$unmute_reason``.
Templates are validated (rendered sample must parse as JSON) at save time.
"""

import json
import string
import requests
from django.utils import timezone

from django import forms
from django.template.defaultfilters import truncatechars

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue
from .base import BaseWebhookBackend
from .webhook_security import validate_webhook_url


def _build_raw_context(summary, issue_title, issue_url, project, alert_reason, issue_id, issue_friendly_id,
                       unmute_reason):
    """Single definition of the template placeholder key set (shared by the config-time
    JSON validation, the alert task and the test-message task, so they can't drift)."""
    return {
        "summary": summary,
        "issue_title": issue_title,
        "issue_url": issue_url,
        "project": project,
        "alert_reason": alert_reason,
        "issue_id": issue_id,
        "issue_friendly_id": issue_friendly_id,
        "unmute_reason": unmute_reason,
    }


def _sample_raw_context():
    """Representative values for every placeholder, used to validate a template at save time."""
    return _build_raw_context(
        summary="NEW issue: Example error - " + get_settings().BASE_URL,
        issue_title="Example error",
        issue_url=get_settings().BASE_URL,
        project="Example project",
        alert_reason="NEW",
        issue_id="1",
        issue_friendly_id="PROJ-42",
        unmute_reason=None,
    )


def _render_body(body_template, raw_context, default_data):
    """Render the request body.

    With a (non-empty) body_template: substitute JSON-encoded values into the
    user's string.Template. Otherwise: serialize the default payload.
    """
    if body_template:
        context = {key: json.dumps(value) for key, value in raw_context.items()}
        return string.Template(body_template).safe_substitute(context)
    return json.dumps(default_data)


class GenericWebhookConfigForm(forms.Form):
    webhook_url = forms.URLField(required=True)
    body_template = forms.CharField(
        required=False,
        strip=False,
        widget=forms.Textarea,
        help_text='Optional. A string.Template body; placeholders expand to JSON-encoded values, '
                  'e.g. {"text": $summary, "url": $issue_url}. Leave blank for the default payload.',
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)

        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")
            self.fields["body_template"].initial = config.get("body_template", "")

    def get_config(self):
        return {
            "webhook_url": self.cleaned_data.get("webhook_url"),
            "body_template": self.cleaned_data.get("body_template"),
        }

    def clean_webhook_url(self):
        webhook_url = self.cleaned_data["webhook_url"]
        try:
            validate_webhook_url(webhook_url)
        except ValueError as e:
            raise forms.ValidationError(str(e)) from e
        return webhook_url

    def clean_body_template(self):
        body_template = self.cleaned_data.get("body_template")
        if body_template:
            context = {key: json.dumps(value) for key, value in _sample_raw_context().items()}
            rendered = string.Template(body_template).safe_substitute(context)
            try:
                json.loads(rendered)
            except (json.JSONDecodeError, ValueError) as e:
                raise forms.ValidationError(
                    'Body template must render to valid JSON. Put a bare $placeholder where a JSON value '
                    'belongs, e.g. {"text": $summary}. (rendered output was not valid JSON: %(err)s)',
                    params={"err": str(e)},
                ) from e
        return body_template


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
                config.last_failure_response_text = response.text[:2000]  # Limit response text size

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


@shared_task
def webhook_backend_send_test_message(webhook_url, project_name, display_name, service_config_id, body_template=None):
    summary = f"Test message by Bugsink to test the webhook setup (project: {project_name}, backend: {display_name})."

    raw_context = _build_raw_context(
        summary=summary,
        issue_title="Test issue",
        issue_url=get_settings().BASE_URL,
        project=project_name,
        alert_reason="TEST",
        issue_id="test",
        issue_friendly_id="PROJ-42",
        unmute_reason=None,
    )
    default_data = {
        "text": summary,
        "issue": None,
    }
    body = _render_body(body_template, raw_context, default_data)

    try:
        result = WebhookBackend.safe_post(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )

        result.raise_for_status()

        _store_success_info(service_config_id)
    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


@shared_task
def webhook_backend_send_alert(
        webhook_url, issue_id, state_description, alert_article, alert_reason, service_config_id,
        unmute_reason=None, body_template=None):

    issue = Issue.objects.get(id=issue_id)

    issue_url = get_settings().BASE_URL + issue.get_absolute_url()
    title = truncatechars(issue.title(), 200)
    summary = f"{alert_reason} issue: {title} - {issue_url}"

    raw_context = _build_raw_context(
        summary=summary,
        issue_title=title,
        issue_url=issue_url,
        project=issue.project.name,
        alert_reason=alert_reason,
        issue_id=str(issue.id),
        issue_friendly_id=issue.friendly_id(),
        unmute_reason=unmute_reason,
    )
    default_data = {
        "text": summary,
        "issue": {
            "title": title,
            "url": issue_url,
            "project": issue.project.name,
            "state": alert_reason,
        },
        "unmute_reason": unmute_reason,
    }
    body = _render_body(body_template, raw_context, default_data)

    try:
        result = WebhookBackend.safe_post(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )

        result.raise_for_status()

        _store_success_info(service_config_id)
    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


class WebhookBackend(BaseWebhookBackend):
    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return GenericWebhookConfigForm

    def send_test_message(self):
        config = json.loads(self.service_config.config)
        webhook_backend_send_test_message.delay(
            config["webhook_url"],
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
            body_template=config.get("body_template"),
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)
        webhook_backend_send_alert.delay(
            config["webhook_url"],
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            body_template=config.get("body_template"),
            **kwargs,
        )
