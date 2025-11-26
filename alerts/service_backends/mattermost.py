import json
import requests
from django.utils import timezone

from django import forms
from django.template.defaultfilters import truncatechars

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


class MattermostConfigForm(forms.Form):
    webhook_url = forms.URLField(required=True)
    channel = forms.CharField(
        required=False,
        help_text='Optional: Override channel (e.g., "town-square" or "@username" for DMs)',
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)

        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")
            self.fields["channel"].initial = config.get("channel", "")

    def get_config(self):
        return {
            "webhook_url": self.cleaned_data.get("webhook_url"),
            "channel": self.cleaned_data.get("channel"),
        }


def _safe_markdown(text):
    # Mattermost uses similar markdown escaping as Slack
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("*", "\\*").replace("_", "\\_")


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
def mattermost_backend_send_test_message(webhook_url, project_name, display_name, service_config_id, channel=None):
    # See https://developers.mattermost.com/integrate/reference/message-attachments/

    data = {"text": "### Test message by Bugsink to test the webhook setup.",
            "attachments": [
                {
                    "title": "TEST issue",
                    "text": "Test message by Bugsink to test the webhook setup.",
                    "fields": [
                        {
                            "title": "project",
                            "value": _safe_markdown(project_name),
                        },
                        {
                            "title": "message backend",
                            "value": _safe_markdown(display_name),
                        },
                    ]
                }
            ]}

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
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


@shared_task
def mattermost_backend_send_alert(
        webhook_url, issue_id, state_description, alert_article, alert_reason, service_config_id, unmute_reason=None,
        channel=None):

    issue = Issue.objects.get(id=issue_id)

    issue_url = get_settings().BASE_URL + issue.get_absolute_url()
    link = f"<{issue_url}|" + _safe_markdown(truncatechars(issue.title().replace("|", ""), 200)) + ">"

    data = {"text": "### " + _safe_markdown(truncatechars(issue.title().replace("|", ""), 200)),
            "attachments": [
                {
                    "title": f"{alert_reason} issue",
                    "text": link,
                    "fields": [],
                }
            ]}

    if unmute_reason:
        data["attachments"][0]["text"] += "\n\n" + _safe_markdown(unmute_reason)

    # assumption: visavis email, project.name is of less importance, because in slack-like things you may (though not
    # always) do one-channel per project. more so for site_title (if you have multiple Bugsinks, you'll surely have
    # multiple slack channels)
    fields = [{
        "title": "Project",
        "value": _safe_markdown(issue.project.name),
    }]

    # left as a (possible) TODO, because the amount of refactoring (passing event to this function) is too big for now
    # if event.release:
    #     fields.append({"title": "Release", "value": _safe_markdown(event.release)})
    # if event.environment:
    #     fields.append("title": "Environment", "value": _safe_markdown(event.environment)})

    data["attachments"][0]["fields"] += fields

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
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


class MattermostBackend:
    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
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

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)
        mattermost_backend_send_alert.delay(
            config["webhook_url"],
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            channel=config.get("channel"),
            **kwargs,
        )
