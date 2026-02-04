"""
Bugsink Messaging Backend: Jira Cloud
======================================

Creates bug tickets in Jira Cloud when issues occur in Bugsink.

Requirements:
    - Jira Cloud instance with API access
    - User email associated with the API token
    - API Token with project write permissions

Setup:
    1. Go to: https://id.atlassian.com/manage-profile/security/api-tokens
    2. Click "Create API token"
    3. Give it a label (e.g., "Bugsink Integration")
    4. Copy the generated token (you won't see it again)
    5. Use your Atlassian account email as the User Email
"""

import json
import requests
from base64 import b64encode

from django import forms
from django.utils import timezone

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


# Standard Jira Issue Types (Cloud)
JIRA_ISSUE_TYPE_CHOICES = [
    ("Bug", "Bug"),
    ("Task", "Task"),
    ("Story", "Story"),
    ("Epic", "Epic"),
    ("Sub-task", "Sub-task"),
    ("Improvement", "Improvement"),
    ("New Feature", "New Feature"),
]


class JiraCloudConfigForm(forms.Form):
    """Configuration form for Jira Cloud integration."""

    jira_url = forms.URLField(
        label="Jira URL",
        help_text="Your Jira Cloud URL, e.g., https://your-domain.atlassian.net",
        widget=forms.URLInput(attrs={"placeholder": "https://your-domain.atlassian.net"}),
    )
    user_email = forms.EmailField(
        label="User Email",
        help_text="Email address associated with the API token",
    )
    api_token = forms.CharField(
        label="API Token",
        help_text="Jira API token (create at id.atlassian.com)",
        widget=forms.PasswordInput(render_value=True),
    )
    project_key = forms.CharField(
        label="Project Key",
        help_text="Jira project key, e.g., 'BUG' or 'PROJ'",
        max_length=20,
        initial="PROJ",
    )
    issue_type = forms.ChoiceField(
        label="Issue Type",
        help_text="Type of issue to create",
        choices=JIRA_ISSUE_TYPE_CHOICES,
        initial="Bug",
    )
    labels = forms.CharField(
        label="Labels (optional)",
        help_text="Comma-separated labels to add, e.g., 'bugsink,production'",
        required=False,
    )
    only_new_issues = forms.BooleanField(
        label="Only New Issues",
        help_text="Create tickets only for NEW issues (recommended to avoid duplicates).",
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={
            "class": "!w-auto !p-0 dark:bg-slate-900 checked:dark:bg-cyan-500 border-cyan-800 "
                     "dark:border-cyan-400 text-cyan-500 dark:text-cyan-300 focus:ring-cyan-200 "
                     "dark:focus:ring-cyan-700 cursor-pointer h-5 w-5"
        }),
    )

    def __init__(self, *args, **kwargs):
        config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)
        if config:
            self.fields["jira_url"].initial = config.get("jira_url", "")
            self.fields["user_email"].initial = config.get("user_email", "")
            self.fields["api_token"].initial = config.get("api_token", "")
            self.fields["project_key"].initial = config.get("project_key", "PROJ")
            self.fields["issue_type"].initial = config.get("issue_type", "Bug")
            self.fields["labels"].initial = ",".join(config.get("labels", []))
            self.fields["only_new_issues"].initial = config.get("only_new_issues", True)

    def get_config(self):
        return {
            "jira_url": self.cleaned_data["jira_url"].rstrip("/"),
            "user_email": self.cleaned_data["user_email"],
            "api_token": self.cleaned_data["api_token"],
            "project_key": self.cleaned_data["project_key"],
            "issue_type": self.cleaned_data["issue_type"],
            "labels": [label.strip() for label in self.cleaned_data.get("labels", "").split(",") if label.strip()],
            "only_new_issues": self.cleaned_data.get("only_new_issues", True),
        }


def _get_auth_header(email: str, api_token: str) -> str:
    """Create Basic Auth header for Jira API."""
    credentials = f"{email}:{api_token}"
    encoded = b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


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
def jira_cloud_backend_send_test_message(jira_url, user_email, api_token, project_key,
                                          issue_type, labels, project_name,
                                          display_name, service_config_id):
    """Send a test message to verify Jira configuration."""
    url = f"{jira_url}/rest/api/3/issue"

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": f"[Bugsink Test] {project_name} - Configuration Verified"[:255],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": (
                            f"This is a test issue created by Bugsink to verify the Jira integration.\n\n"
                            f"Project: {project_name}\n"
                            f"Service: {display_name}\n\n"
                            "If you see this issue, your configuration is working correctly.\n"
                            "You can safely delete this issue."
                        )}]
                    }
                ]
            },
            "issuetype": {"name": issue_type},
        }
    }

    if labels:
        payload["fields"]["labels"] = labels

    try:
        result = requests.post(
            url,
            data=json.dumps(payload),
            headers={
                "Authorization": _get_auth_header(user_email, api_token),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
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
def jira_cloud_backend_send_alert(jira_url, user_email, api_token, project_key,
                                   issue_type, labels, issue_id, state_description,
                                   alert_article, alert_reason, service_config_id,
                                   unmute_reason=None):
    """Create a Jira issue for a Bugsink alert."""
    issue = Issue.objects.get(id=issue_id)
    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    summary = f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}"

    description_lines = [
        f"Error Type: {issue.calculated_type or 'Unknown'}",
        f"Error Message: {issue.calculated_value or 'No message'}",
        "",
        f"View in Bugsink: {issue_url}",
        "",
        f"First Seen: {issue.first_seen.isoformat() if issue.first_seen else 'Unknown'}",
        f"Last Seen: {issue.last_seen.isoformat() if issue.last_seen else 'Unknown'}",
        f"Event Count: {issue.digested_event_count}",
        "",
        f"Project: {issue.project.name}",
        f"Alert Type: {state_description}",
        f"Reason: {alert_reason}",
    ]

    if unmute_reason:
        description_lines.append(f"Unmute Reason: {unmute_reason}")

    url = f"{jira_url}/rest/api/3/issue"

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary[:255],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "\n".join(description_lines)}]
                    }
                ]
            },
            "issuetype": {"name": issue_type},
        }
    }

    if labels:
        payload["fields"]["labels"] = labels

    try:
        result = requests.post(
            url,
            data=json.dumps(payload),
            headers={
                "Authorization": _get_auth_header(user_email, api_token),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30,
        )
        result.raise_for_status()
        _store_success_info(service_config_id)

    except requests.RequestException as e:
        response = getattr(e, 'response', None)
        _store_failure_info(service_config_id, e, response)

    except Exception as e:
        _store_failure_info(service_config_id, e)


class JiraCloudBackend:
    """Backend class for Jira Cloud integration."""

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return JiraCloudConfigForm

    def send_test_message(self):
        config = json.loads(self.service_config.config)
        jira_cloud_backend_send_test_message.delay(
            config["jira_url"],
            config["user_email"],
            config["api_token"],
            config["project_key"],
            config["issue_type"],
            config.get("labels", []),
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        config = json.loads(self.service_config.config)

        # Check if we should only create tickets for NEW issues
        if config.get("only_new_issues", True) and state_description != "NEW":
            return

        jira_cloud_backend_send_alert.delay(
            config["jira_url"],
            config["user_email"],
            config["api_token"],
            config["project_key"],
            config["issue_type"],
            config.get("labels", []),
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            **kwargs,
        )
