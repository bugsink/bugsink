import json
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


class MsTeamsConfigForm(forms.Form):
    # Workflow ("Post to a channel when a webhook request is received") URLs are much longer than the 200 chars that
    # URLField defaults to.
    webhook_url = forms.URLField(required=True, assume_scheme="https", max_length=1000)

    # Microsoft Teams does not support multi-channel webhooks: the channel is picked when the workflow is created.

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)

        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")

    def get_config(self):
        return {
            "webhook_url": self.cleaned_data.get("webhook_url"),
        }

    def clean_webhook_url(self):
        webhook_url = self.cleaned_data["webhook_url"]
        try:
            validate_webhook_url(webhook_url)
        except ValueError as e:
            raise forms.ValidationError(str(e)) from e
        return webhook_url


def _safe_markdown(text):
    # Adaptive Card TextBlocks render a subset of markdown; escape the characters that carry meaning in it.
    return (text.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_")
                .replace("[", "\\[").replace("]", "\\]").replace("#", "\\#").replace("-", "\\-"))


def _as_message(card_body, actions=None):
    # Teams expects an Adaptive Card wrapped in an attachment; see
    # https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-reference
    content = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": card_body,
    }

    if actions:
        content["actions"] = actions

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": content,
            }
        ],
    }


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
def msteams_backend_send_test_message(webhook_url, project_name, display_name, service_config_id):
    data = _as_message([
        {
            "type": "TextBlock",
            "text": "TEST issue",
            "size": "Large",
            "weight": "Bolder",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": "Test message by Bugsink to test the webhook setup.",
            "wrap": True,
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "project", "value": _safe_markdown(project_name)},
                {"title": "message backend", "value": _safe_markdown(display_name)},
            ],
        },
    ])

    try:
        result = MsTeamsBackend.safe_post(
            webhook_url,
            data=json.dumps(data),
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
def msteams_backend_send_alert(
        webhook_url, issue_id, state_description, alert_article, alert_reason, service_config_id, unmute_reason=None):

    issue = Issue.objects.get(id=issue_id)

    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    body = [
        {
            "type": "TextBlock",
            "text": _safe_markdown(truncatechars(issue.title(), 150)),
            "size": "Large",
            "weight": "Bolder",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": f"{alert_reason} issue",
            "wrap": True,
        },
    ]

    if unmute_reason:
        body.append({
            "type": "TextBlock",
            "text": _safe_markdown(unmute_reason),
            "wrap": True,
        })

    # assumption: visavis email, project.name is of less importance, because in slack-like things you may (though not
    # always) do one-channel per project. more so for site_title (if you have multiple Bugsinks, you'll surely have
    # multiple teams channels)
    facts = [{"title": "project", "value": _safe_markdown(issue.project.name)}]

    # left as a (possible) TODO, because the amount of refactoring (passing event to this function) is too big for now
    # if event.release:
    #     facts.append({"title": "release", "value": _safe_markdown(event.release)})
    # if event.environment:
    #     facts.append({"title": "environment", "value": _safe_markdown(event.environment)})

    body.append({"type": "FactSet", "facts": facts})

    data = _as_message(body, actions=[
        {
            "type": "Action.OpenUrl",
            "title": "view on Bugsink",
            "url": issue_url,
        },
    ])

    try:
        result = MsTeamsBackend.safe_post(
            webhook_url,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
        )

        result.raise_for_status()

        _store_success_info(service_config_id)
    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


class MsTeamsBackend(BaseWebhookBackend):
    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return MsTeamsConfigForm

    def send_test_message(self):
        config = json.loads(self.service_config.config)
        msteams_backend_send_test_message.delay(
            config["webhook_url"],
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)
        msteams_backend_send_alert.delay(
            config["webhook_url"],
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            **kwargs,
        )
