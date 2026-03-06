from urllib.parse import urlparse
import json
import requests
from random import random
from django.utils import timezone

from django import forms

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


def url_valid_according_to_teams(url):
    # Placeholder for potential webhook url validation
    parsed = urlparse(url)
    return (
        parsed.scheme in ("http", "https")
        and parsed.hostname is not None
        and "." in parsed.hostname
    )


class TeamsConfigForm(forms.Form):
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


def _teams_generate_tablerow(left_column, right_column):
    return {
        "type": "TableRow",
        "cells": [
            {
                "type": "TableCell",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": left_column,
                        "wrap": True,
                        "weight": "Bolder"
                    }
                ]
            },
            {
                "type": "TableCell",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": right_column,
                        "wrap": True,
                        "weight": "Lighter"
                    }
                ]
            }
        ]
    }


def _teams_generate_message(project_name, issue_id, issue_title, alert_reason, issue_url, unmute_reason=None):
    """ generate a message in Microsoft Teams adaptive card format """
    """ See https://adaptivecards.microsoft.com/designer """

    message = {
        "type": "AdaptiveCard",
        "speak": "Error",
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": []
    }

    base_info = {
        "type": "ColumnSet",
        "columns": [
            {
                "type": "Column",
                "width": "auto",
                "items": [
                    {
                        "type": "Icon",
                        "name": "Bug",
                        "size": "Medium",
                        "color": "Dark",
                        "style": "Filled"
                    }
                ]
            },
            {
                "type": "Column",
                "width": "stretch",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": issue_title,
                        "wrap": True,
                        "weight": "Bolder"
                    }
                 ]
            },
            {
                "type": "Column",
                "width": "auto",
                "items": [
                    {
                        "type": "Badge",
                        "text": "New!",
                        "style": "Attention"
                    }
                ]
            }
        ]
    }

    table_info = {
        "type": "Table",
        "showGridLines": False,
        "columns": [
            {
                "width": 1
            },
            {
                "width": 1
            }
        ],
        "rows": [
            _teams_generate_tablerow("Project:", project_name),
            _teams_generate_tablerow("Reason:", alert_reason),
            _teams_generate_tablerow("Id:", issue_id)
        ]
    }

    if unmute_reason:
        table_info["rows"].append(_teams_generate_tablerow("Unmute Reason:", unmute_reason))

    actions = {
        "type": "ActionSet",
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Open in Bugsink",
                "url": issue_url,
                "iconUrl": "icon:BookOpenGlobe"
            }
        ]
    }

    message["body"].append(base_info)
    message["body"].append(table_info)
    message["body"].append(actions)

    return message


@shared_task
def teams_backend_send_test_message(
    webhook_url, project_name, display_name, service_config_id
):
    message_json = _teams_generate_message(
            project_name,
            "test issue_id",
            f"test issue_title {random()}",
            "test alert_reason",
            "https://bugsink.com/",
            "test unmute_reason")

    try:
        result = requests.post(
            webhook_url,
            data=json.dumps(message_json),
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
def teams_backend_send_alert(
        webhook_url, issue_id, state_description, alert_article, alert_reason, service_config_id, unmute_reason=None):

    issue = Issue.objects.get(id=issue_id)
    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    message_json = _teams_generate_message(
            issue.project.name,
            issue_id,
            issue.title(),
            alert_reason,
            issue_url,
            unmute_reason=None)

    try:
        result = requests.post(
            webhook_url,
            data=json.dumps(message_json),
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


class TeamsBackend:

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return TeamsConfigForm

    def send_test_message(self):
        teams_backend_send_test_message.delay(
            json.loads(self.service_config.config)["webhook_url"],
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)
        teams_backend_send_alert.delay(
            config["webhook_url"],
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            **kwargs,
        )
