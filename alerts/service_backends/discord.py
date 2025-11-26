from urllib.parse import urlparse
import json
import requests
from django.utils import timezone

from django import forms
from django.template.defaultfilters import truncatechars

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


def url_valid_according_to_discord(url):
    # See https://github.com/bugsink/bugsink/issues/280 for "according to Discord"
    parsed = urlparse(url)
    return (
        parsed.scheme in ("http", "https")
        and parsed.hostname is not None
        and "." in parsed.hostname
    )


class DiscordConfigForm(forms.Form):
    webhook_url = forms.URLField(required=True)

    # Discord does not appear to support multi-channel webhooks; although this is not spelled out explicitly, the
    # section at https://discord.com/developers/docs/resources/webhook#execute-webhook does not have an attr for
    # "channel". (the word channel appears on that page, but that's for the _creation_ of new webhooks).

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)

        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")

    def get_config(self):
        return {
            "webhook_url": self.cleaned_data.get("webhook_url"),
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
def discord_backend_send_test_message(
    webhook_url, project_name, display_name, service_config_id
):
    # Discord uses embeds for rich formatting
    # Color: 0x7289DA is Discord's blurple color

    data = {
        "embeds": [
            {
                "title": "TEST issue",
                "description": "Test message by Bugsink to test the webhook setup.",
                "color": 0x7289DA,
                "fields": [
                    {"name": "Project", "value": project_name, "inline": True},
                    {"name": "Message Backend", "value": display_name, "inline": True},
                ],
            }
        ]
    }

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
def discord_backend_send_alert(
        webhook_url, issue_id, state_description, alert_article, alert_reason, service_config_id, unmute_reason=None):

    issue = Issue.objects.get(id=issue_id)

    issue_url = get_settings().BASE_URL + issue.get_absolute_url()
    issue_title = truncatechars(issue.title(), 256)  # Discord title limit

    # Color coding based on alert reason
    # Red for new issues, orange for recurring, blue for unmuted
    color_map = {
        "NEW": 0xE74C3C,  # Red
        "RECURRING": 0xE67E22,  # Orange
        "UNMUTED": 0x3498DB,  # Blue
    }
    color = color_map.get(alert_reason, 0x95A5A6)  # Gray as default

    embed = {
        "title": issue_title,
        "description": f"{alert_reason} issue",
        "color": color,
        "fields": [{"name": "Project", "value": issue.project.name, "inline": True}],
    }

    if url_valid_according_to_discord(issue_url):
        embed["url"] = issue_url

    if unmute_reason:
        embed["fields"].append(
            {"name": "Unmute Reason", "value": unmute_reason, "inline": False}
        )

    # left as a (possible) TODO, because the amount of refactoring (passing event to this function) is too big for now
    # if event.release:
    #     embed["fields"].append({
    #         "name": "Release",
    #         "value": event.release,
    #         "inline": True
    #     })
    # if event.environment:
    #     embed["fields"].append({
    #         "name": "Environment",
    #         "value": event.environment,
    #         "inline": True
    #     })

    data = {"embeds": [embed]}

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


class DiscordBackend:

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return DiscordConfigForm

    def send_test_message(self):
        discord_backend_send_test_message.delay(
            json.loads(self.service_config.config)["webhook_url"],
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)
        discord_backend_send_alert.delay(
            config["webhook_url"],
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            **kwargs,
        )
