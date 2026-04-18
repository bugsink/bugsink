import html
import json
import re

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
CHAT_ID_RE = re.compile(r"^-?\d+$")
CHANNEL_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]+$")


def _build_webhook_url(bot_token):
    return f"https://api.telegram.org/bot{bot_token}/sendMessage"


def _chat_id_supports_message_thread_id(chat_id):
    # Chat ID requirement is validated by form field
    if chat_id is None:
        return True
    return not chat_id.startswith("@")


class TelegramConfigForm(forms.Form):
    bot_token = forms.CharField(
        required=True,
        strip=True,
        help_text="Telegram bot token (from https://t.me/BotFather)",
    )
    chat_id = forms.CharField(
        required=True,
        strip=True,
        help_text='Chat ID or channel username (e.g. "-1001234567890" or "@channelusername")',
    )
    message_thread_id = forms.IntegerField(
        required=False,
        min_value=1,
        help_text="Optional: Topic ID for Telegram groups with topics enabled",
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)

        super().__init__(*args, **kwargs)
        if config:
            self.fields["bot_token"].initial = config.get("bot_token", "")
            self.fields["chat_id"].initial = config.get("chat_id", "")
            self.fields["message_thread_id"].initial = config.get("message_thread_id", "")

    def get_config(self):
        return {
            "bot_token": self.cleaned_data.get("bot_token"),
            "chat_id": self.cleaned_data.get("chat_id"),
            "message_thread_id": self.cleaned_data.get("message_thread_id"),
        }

    def clean_bot_token(self):
        bot_token = self.cleaned_data["bot_token"]
        webhook_url = _build_webhook_url(bot_token)
        try:
            validate_webhook_url(webhook_url)
        except ValueError as e:
            raise forms.ValidationError(str(e)) from e
        return bot_token

    def clean_chat_id(self):
        chat_id = self.cleaned_data["chat_id"]

        if chat_id.startswith("@"):
            if not CHANNEL_USERNAME_RE.fullmatch(chat_id):
                raise forms.ValidationError("Channel username must be in the format @channelusername.")
            return chat_id

        if not CHAT_ID_RE.fullmatch(chat_id):
            raise forms.ValidationError("Chat ID must be a numeric chat ID or @channelusername.")
        return chat_id

    def clean(self):
        cleaned_data = super().clean()
        chat_id = cleaned_data.get("chat_id")
        message_thread_id = cleaned_data.get("message_thread_id")

        if not _chat_id_supports_message_thread_id(chat_id) and message_thread_id is not None:
            self.add_error("message_thread_id", "Topic ID can only be used with numeric chat IDs.")

        return cleaned_data


def _safe_html(text):
    # Telegram uses HTML parse mode, so escape special characters in message content.
    return html.escape(text)


def _store_failure_info(service_config_id, exception, response=None, bot_token=None):
    """Store failure information in the MessagingServiceConfig with immediate_atomic"""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)

            error_message = str(exception)
            if bot_token:
                error_message = error_message.replace(bot_token, MASKED)

            config.last_failure_timestamp = timezone.now()
            config.last_failure_error_type = type(exception).__name__
            config.last_failure_error_message = error_message

            # Handle requests-specific errors
            if response is not None:
                response_text = response.text
                if bot_token:
                    response_text = response_text.replace(bot_token, MASKED)

                config.last_failure_status_code = response.status_code
                config.last_failure_response_text = response_text[:2000]  # Limit response text size

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


def _build_test_message(project_name, display_name):
    return (
        "<b>TEST issue</b>\n\n"
        "Test message by Bugsink to test the webhook setup.\n\n"
        "<b>Project:</b> " + _safe_html(project_name) + "\n"
        "<b>Message Backend:</b> " + _safe_html(display_name)
    )


def _build_alert_message(issue, alert_reason, issue_url, unmute_reason=None):
    text = (
        "<b>" + _safe_html(truncatechars(issue.title(), 200)) + "</b>\n\n"
        f"{alert_reason} issue\n\n"
        "<b>Project:</b> " + _safe_html(issue.project.name)
    )

    if unmute_reason:
        text += "\n\n<b>Unmute Reason:</b> " + _safe_html(unmute_reason)

    text += '\n\n<a href="' + html.escape(issue_url, quote=True) + '">View on Bugsink</a>'
    return text


@shared_task
def telegram_backend_send_test_message(
    webhook_url, bot_token, chat_id, project_name, display_name, service_config_id, message_thread_id=None
):
    data = {
        "chat_id": chat_id,
        "text": _build_test_message(project_name, display_name),
        "parse_mode": "HTML",
    }

    if message_thread_id is not None and _chat_id_supports_message_thread_id(chat_id):
        data["message_thread_id"] = message_thread_id

    try:
        result = TelegramBackend.safe_post(
            webhook_url,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
        )

        result.raise_for_status()

        _store_success_info(service_config_id)
    except requests.RequestException as e:
        response = getattr(e, "response", None)
        _store_failure_info(service_config_id, e, response, bot_token)

    except Exception as e:
        _store_failure_info(service_config_id, e, bot_token=bot_token)


@shared_task
def telegram_backend_send_alert(
    webhook_url,
    bot_token,
    chat_id,
    issue_id,
    state_description,
    alert_article,
    alert_reason,
    service_config_id,
    unmute_reason=None,
    message_thread_id=None,
):

    issue = Issue.objects.get(id=issue_id)

    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    data = {
        "chat_id": chat_id,
        "text": _build_alert_message(issue, alert_reason, issue_url, unmute_reason=unmute_reason),
        "parse_mode": "HTML",
    }

    if message_thread_id is not None and _chat_id_supports_message_thread_id(chat_id):
        data["message_thread_id"] = message_thread_id

    try:
        result = TelegramBackend.safe_post(
            webhook_url,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
        )

        result.raise_for_status()

        _store_success_info(service_config_id)
    except requests.RequestException as e:
        response = getattr(e, "response", None)
        _store_failure_info(service_config_id, e, response, bot_token)

    except Exception as e:
        _store_failure_info(service_config_id, e, bot_token=bot_token)


class TelegramBackend(BaseWebhookBackend):
    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return TelegramConfigForm

    def send_test_message(self):
        config = json.loads(self.service_config.config)
        bot_token = config["bot_token"]
        telegram_backend_send_test_message.delay(
            _build_webhook_url(bot_token),
            bot_token,
            config["chat_id"],
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
            message_thread_id=config.get("message_thread_id"),
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)
        bot_token = config["bot_token"]
        telegram_backend_send_alert.delay(
            _build_webhook_url(bot_token),
            bot_token,
            config["chat_id"],
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            message_thread_id=config.get("message_thread_id"),
            **kwargs,
        )
