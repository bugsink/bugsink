"""
Bugsink Messaging Backend: Jira Cloud
======================================

Creates bug tickets in Jira Cloud when issues occur in Bugsink.

Compatible with Bugsink v2.

Installation:
    Copy to: /app/alerts/service_backends/jira_cloud.py
    Register in: /app/alerts/models.py

Requirements:
    - Jira Cloud instance with API access
    - API Token (create at: https://id.atlassian.com/manage-profile/security/api-tokens)
    - User email associated with the API token
"""

import json
import logging
from base64 import b64encode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from django import forms
from django.utils import timezone

from snappea.decorators import shared_task
from bugsink.transaction import immediate_atomic

logger = logging.getLogger(__name__)


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
        initial="error-observer",
        required=False,
    )
    only_new_issues = forms.BooleanField(
        label="Only New Issues",
        help_text="Create tickets only for NEW issues (recommended to avoid duplicates). Uncheck to also create tickets for regressions and unmutes.",
        initial=True,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        """Initialize form with existing config if provided."""
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
        """Return configuration dict to be JSON serialized and stored."""
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
    """Store failure info in MessagingServiceConfig using individual fields."""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)
            config.last_failure_timestamp = timezone.now()
            config.last_failure_error_type = type(exception).__name__
            config.last_failure_error_message = str(exception)[:2000]

            if response is not None:
                # For urllib, we need to handle differently than requests
                if hasattr(response, 'status'):
                    config.last_failure_status_code = response.status
                elif hasattr(response, 'code'):
                    config.last_failure_status_code = response.code
                else:
                    config.last_failure_status_code = None

                response_text = getattr(response, 'text', None)
                if response_text:
                    config.last_failure_response_text = response_text[:2000]
                    try:
                        json.loads(response_text)
                        config.last_failure_is_json = True
                    except (json.JSONDecodeError, ValueError):
                        config.last_failure_is_json = False
                else:
                    config.last_failure_response_text = None
                    config.last_failure_is_json = None
            else:
                config.last_failure_status_code = None
                config.last_failure_response_text = None
                config.last_failure_is_json = None

            config.save()
        except MessagingServiceConfig.DoesNotExist:
            logger.warning(f"MessagingServiceConfig {service_config_id} not found for failure tracking")


def _store_success_info(service_config_id):
    """Clear failure info on successful operation."""
    from alerts.models import MessagingServiceConfig

    with immediate_atomic(only_if_needed=True):
        try:
            config = MessagingServiceConfig.objects.get(id=service_config_id)
            config.clear_failure_status()
            config.save()
        except MessagingServiceConfig.DoesNotExist:
            pass


def _create_jira_issue(config: dict, summary: str, description: str) -> dict:
    """Create a Jira issue via REST API."""
    url = f"{config['jira_url']}/rest/api/3/issue"

    # Build Atlassian Document Format description
    payload = {
        "fields": {
            "project": {"key": config["project_key"]},
            "summary": summary[:255],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}]
                    }
                ]
            },
            "issuetype": {"name": config["issue_type"]},
        }
    }

    if config.get("labels"):
        payload["fields"]["labels"] = config["labels"]

    headers = {
        "Authorization": _get_auth_header(config["user_email"], config["api_token"]),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


@shared_task
def jira_cloud_backend_send_test_message(jira_url, user_email, api_token, project_key,
                                          issue_type, labels, project_name,
                                          display_name, service_config_id):
    """Send a test message to verify Jira configuration."""
    config = {
        "jira_url": jira_url,
        "user_email": user_email,
        "api_token": api_token,
        "project_key": project_key,
        "issue_type": issue_type,
        "labels": labels,
    }

    try:
        result = _create_jira_issue(
            config,
            summary=f"[Bugsink Test] {project_name} - Configuration Verified",
            description=(
                f"This is a test issue created by Bugsink to verify the Jira integration.\n\n"
                f"Project: {project_name}\n"
                f"Service: {display_name}\n\n"
                "If you see this issue, your configuration is working correctly.\n"
                "You can safely delete this issue."
            ),
        )

        _store_success_info(service_config_id)
        logger.info(f"Jira test issue created: {result.get('key')}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"Jira API error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"Jira connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending to Jira: {e}")
        _store_failure_info(service_config_id, e)


@shared_task
def jira_cloud_backend_send_alert(jira_url, user_email, api_token, project_key,
                                   issue_type, labels, issue_id, state_description,
                                   alert_article, alert_reason, service_config_id,
                                   bugsink_base_url=None, unmute_reason=None):
    """Create a Jira issue for a Bugsink alert."""
    from issues.models import Issue

    config = {
        "jira_url": jira_url,
        "user_email": user_email,
        "api_token": api_token,
        "project_key": project_key,
        "issue_type": issue_type,
        "labels": labels,
    }

    # Build issue URL using same path as Slack backend
    issue_url = None
    if bugsink_base_url:
        issue_url = f"{bugsink_base_url.rstrip('/')}/issues/issue/{issue_id}/event/last/"

    try:
        issue = Issue.objects.select_related("project").get(pk=issue_id)

        summary = f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}"

        description_lines = [
            f"Error Type: {issue.calculated_type or 'Unknown'}",
            f"Error Message: {issue.calculated_value or 'No message'}",
            "",
        ]

        # Add link to Bugsink issue
        if issue_url:
            description_lines.append(f"View in Bugsink: {issue_url}")
            description_lines.append("")

        description_lines.extend([
            f"First Seen: {issue.first_seen.isoformat() if issue.first_seen else 'Unknown'}",
            f"Last Seen: {issue.last_seen.isoformat() if issue.last_seen else 'Unknown'}",
            f"Event Count: {issue.digested_event_count}",
            "",
            f"Project: {issue.project.name if issue.project else 'Unknown'}",
            f"Alert Type: {state_description}",
            f"Reason: {alert_reason}",
        ])

        if unmute_reason:
            description_lines.append(f"Unmute Reason: {unmute_reason}")

        description = "\n".join(description_lines)

    except Issue.DoesNotExist:
        summary = f"[{state_description}] Issue {issue_id}"
        desc_lines = [f"Issue ID: {issue_id}"]
        if issue_url:
            desc_lines.append(f"View in Bugsink: {issue_url}")
        desc_lines.extend([f"Alert Type: {state_description}", f"Reason: {alert_reason}"])
        description = "\n".join(desc_lines)

    try:
        result = _create_jira_issue(config, summary=summary, description=description)
        _store_success_info(service_config_id)
        logger.info(f"Jira issue created for Bugsink issue {issue_id}: {result.get('key')}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"Jira API error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"Jira connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending to Jira: {e}")
        _store_failure_info(service_config_id, e)


class JiraCloudBackend:
    """Backend class for Jira Cloud integration.

    Compatible with Bugsink v2 backend interface.
    """

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        """Return the configuration form class."""
        return JiraCloudConfigForm

    def send_test_message(self):
        """Dispatch test message task."""
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
        """Dispatch alert task."""
        from bugsink.app_settings import get_settings
        config = json.loads(self.service_config.config)

        # Check if we should only create tickets for NEW issues
        if config.get("only_new_issues", True) and state_description != "NEW":
            logger.debug(f"Skipping Jira ticket for {state_description} issue {issue_id} (only_new_issues=True)")
            return

        # Get base URL from Bugsink settings (same as Slack backend)
        bugsink_base_url = get_settings().BASE_URL

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
            bugsink_base_url=bugsink_base_url,
            **kwargs,
        )
