import json
import requests

from django import forms
from django.template.defaultfilters import truncatechars

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings

from issues.models import Issue


class SlackConfigForm(forms.Form):
    webhook_url = forms.URLField(required=True)

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)

        super().__init__(*args, **kwargs)
        if config:
            self.fields["webhook_url"].initial = config.get("webhook_url", "")

    def get_config(self):
        return {
            "webhook_url": self.cleaned_data.get("webhook_url"),
        }


def _safe_markdown(text):
    # Slack assigns a special meaning to some characters, so we need to escape them
    # to prevent them from being interpreted as formatting/special characters.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("*", "\\*").replace("_", "\\_")


@shared_task
def slack_backend_send_test_message(webhook_url, project_name, display_name):
    # See Slack's Block Kit Builder

    data = {"blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "TEST issue",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Test message by Bugsink to test the webhook setup.",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": "*project*: " + _safe_markdown(project_name),
                        },
                        {
                            "type": "mrkdwn",
                            "text": "*message backend*: " + _safe_markdown(display_name),
                        },
                    ]
                }

            ]}

    result = requests.post(
        webhook_url,
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
    )

    result.raise_for_status()


@shared_task
def slack_backend_send_alert(webhook_url, issue_id, state_description, alert_article, alert_reason, unmute_reason=None):
    issue = Issue.objects.get(id=issue_id)

    issue_url = get_settings().BASE_URL + issue.get_absolute_url()
    link = f"<{issue_url}|" + _safe_markdown(truncatechars(issue.title().replace("|", ""), 200)) + ">"

    sections = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{alert_reason} issue",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": link,
                    },
                },
               ]

    if unmute_reason:
        sections.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": unmute_reason,
            },
        })

    # assumption: visavis email, project.name is of less importance, because in slack-like things you may (though not
    # always) do one-channel per project. more so for site_title (if you have multiple Bugsinks, you'll surely have
    # multiple slack channels)
    fields = {
        "project": issue.project.name
    }

    # left as a (possible) TODO, because the amount of refactoring (passing event to this function) is too big for now
    # if event.release:
    #     fields["release"] = event.release
    # if event.environment:
    #     fields["environment"] = event.environment

    data = {"blocks": sections + [
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*{field}*: " + _safe_markdown(value),
                        } for field, value in fields.items()
                    ]
                },
            ]}

    result = requests.post(
        webhook_url,
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
    )

    result.raise_for_status()


class SlackBackend:

    def __init__(self, service_config):
        self.service_config = service_config

    def get_form_class(self):
        return SlackConfigForm

    def send_test_message(self):
        slack_backend_send_test_message.delay(
            json.loads(self.service_config.config)["webhook_url"],
            self.service_config.project.name,
            self.service_config.display_name,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        slack_backend_send_alert.delay(
            json.loads(self.service_config.config)["webhook_url"],
            issue_id, state_description, alert_article, alert_reason, **kwargs)
