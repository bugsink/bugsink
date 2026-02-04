"""
Bugsink Messaging Backend: GitHub Issues
=========================================

Creates issues in a GitHub repository when errors occur in Bugsink.

Compatible with Bugsink v2.

Installation:
    Copy to: /app/alerts/service_backends/github_issues.py
    Register in: /app/alerts/models.py

Requirements:
    - GitHub repository with Issues enabled
    - Personal Access Token (classic) or Fine-grained token with 'issues:write' permission
    - Create token at: https://github.com/settings/tokens
"""

import json
import logging
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from django import forms
from django.utils import timezone

from snappea.decorators import shared_task
from bugsink.transaction import immediate_atomic

logger = logging.getLogger(__name__)

# GitHub API base URL
GITHUB_API_URL = "https://api.github.com"


class GitHubIssuesConfigForm(forms.Form):
    """Configuration form for GitHub Issues integration."""

    repository = forms.CharField(
        label="Repository",
        help_text="Repository in 'owner/repo' format, e.g., 'myorg/myproject'",
        max_length=200,
        initial="bauer-group/myproject",
        widget=forms.TextInput(attrs={"placeholder": "owner/repository"}),
    )
    access_token = forms.CharField(
        label="Access Token",
        help_text="GitHub Personal Access Token with 'repo' or 'issues:write' scope",
        widget=forms.PasswordInput(render_value=True),
    )
    labels = forms.CharField(
        label="Labels (optional)",
        help_text="Comma-separated labels to add, e.g., 'bug,bugsink,production'",
        initial="bug,error-observer",
        required=False,
    )
    assignees = forms.CharField(
        label="Assignees (optional)",
        help_text="Comma-separated GitHub usernames to assign, e.g., 'user1,user2'",
        required=False,
    )
    only_new_issues = forms.BooleanField(
        label="Only New Issues",
        help_text="Create issues only for NEW errors (recommended to avoid duplicates). Uncheck to also create issues for regressions and unmutes.",
        initial=True,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        """Initialize form with existing config if provided."""
        config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)
        if config:
            self.fields["repository"].initial = config.get("repository", "")
            self.fields["access_token"].initial = config.get("access_token", "")
            self.fields["labels"].initial = ",".join(config.get("labels", []))
            self.fields["assignees"].initial = ",".join(config.get("assignees", []))
            self.fields["only_new_issues"].initial = config.get("only_new_issues", True)

    def clean_repository(self):
        """Validate repository format."""
        repo = self.cleaned_data["repository"].strip()
        if "/" not in repo or repo.count("/") != 1:
            raise forms.ValidationError("Repository must be in 'owner/repo' format")
        owner, name = repo.split("/")
        if not owner or not name:
            raise forms.ValidationError("Both owner and repository name are required")
        return repo

    def get_config(self):
        """Return configuration as dictionary for storage."""
        return {
            "repository": self.cleaned_data["repository"],
            "access_token": self.cleaned_data["access_token"],
            "labels": [l.strip() for l in self.cleaned_data.get("labels", "").split(",") if l.strip()],
            "assignees": [a.strip() for a in self.cleaned_data.get("assignees", "").split(",") if a.strip()],
            "only_new_issues": self.cleaned_data.get("only_new_issues", True),
        }


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


def _format_body(issue_id: str, state_description: str, alert_article: str,
                 alert_reason: str, bugsink_base_url: str = None, **kwargs) -> str:
    """Format alert data as GitHub-flavored Markdown."""
    from issues.models import Issue

    # Build issue URL using same path as Slack backend
    issue_url = None
    if bugsink_base_url:
        issue_url = f"{bugsink_base_url.rstrip('/')}/issues/issue/{issue_id}/event/last/"

    try:
        issue = Issue.objects.select_related("project").get(pk=issue_id)

        lines = [
            "## Error Details",
            "",
            f"**Error Type:** `{issue.calculated_type or 'Unknown'}`",
            f"**Error Message:** {issue.calculated_value or 'No message'}",
            "",
        ]

        # Add link to Bugsink issue
        if issue_url:
            lines.extend([
                f"**View in Bugsink:** [{issue_url}]({issue_url})",
                "",
            ])

        lines.extend([
            "## Timeline",
            "",
            "| First Seen | Last Seen | Event Count |",
            "|------------|-----------|-------------|",
            f"| {issue.first_seen.isoformat() if issue.first_seen else 'Unknown'} | {issue.last_seen.isoformat() if issue.last_seen else 'Unknown'} | {issue.digested_event_count} |",
            "",
            "## Context",
            "",
            f"- **Project:** {issue.project.name if issue.project else 'Unknown'}",
            f"- **Alert Type:** {state_description}",
            f"- **Reason:** {alert_reason}",
        ])

        # Add unmute reason if present
        if kwargs.get("unmute_reason"):
            lines.append(f"- **Unmute Reason:** {kwargs['unmute_reason']}")

    except Issue.DoesNotExist:
        lines = [
            "## Error Details",
            "",
            f"**Issue ID:** {issue_id}",
        ]
        if issue_url:
            lines.append(f"**View in Bugsink:** [{issue_url}]({issue_url})")
        lines.extend([
            f"**Alert Type:** {state_description}",
            f"**Reason:** {alert_reason}",
        ])

    lines.extend([
        "",
        "---",
        "*This issue was automatically created by [Bugsink](https://bugsink.com)*",
    ])

    return "\n".join(lines)


def _create_github_issue(config: dict, title: str, body: str) -> dict:
    """Create a GitHub issue via REST API."""
    repo = config["repository"]
    url = f"{GITHUB_API_URL}/repos/{repo}/issues"

    payload = {
        "title": title[:256],  # GitHub title recommendation
        "body": body,
    }

    # Add labels if configured
    if config.get("labels"):
        payload["labels"] = config["labels"]

    # Add assignees if configured
    if config.get("assignees"):
        payload["assignees"] = config["assignees"]

    headers = {
        "Authorization": f"Bearer {config['access_token']}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


@shared_task
def github_issues_send_test_message(repository, access_token, labels, assignees,
                                     project_name, display_name, service_config_id):
    """Send a test issue to verify GitHub configuration."""
    config = {
        "repository": repository,
        "access_token": access_token,
        "labels": labels,
        "assignees": assignees,
    }

    try:
        result = _create_github_issue(
            config,
            title=f"[Bugsink] Test Issue - {project_name}",
            body=(
                "## Test Issue\n\n"
                f"This is a test issue created by **Bugsink** to verify the GitHub integration.\n\n"
                f"- **Project:** {project_name}\n"
                f"- **Service:** {display_name}\n\n"
                "If you see this issue, your configuration is working correctly.\n\n"
                "You can safely close and delete this issue.\n\n"
                "---\n"
                "*Automatically created by [Bugsink](https://bugsink.com)*"
            ),
        )

        _store_success_info(service_config_id)
        logger.info(f"GitHub test issue created: #{result.get('number')} - {result.get('html_url')}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"GitHub API error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"GitHub connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending to GitHub: {e}")
        _store_failure_info(service_config_id, e)


@shared_task
def github_issues_send_alert(repository, access_token, labels, assignees,
                              issue_id, state_description, alert_article, alert_reason,
                              service_config_id, bugsink_base_url=None, unmute_reason=None):
    """Create a GitHub issue for a Bugsink alert."""
    from issues.models import Issue

    config = {
        "repository": repository,
        "access_token": access_token,
        "labels": labels,
        "assignees": assignees,
    }

    try:
        issue = Issue.objects.select_related("project").get(pk=issue_id)
        title = f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}"
    except Issue.DoesNotExist:
        title = f"[{state_description}] Issue {issue_id}"

    body = _format_body(issue_id, state_description, alert_article, alert_reason,
                        bugsink_base_url=bugsink_base_url, unmute_reason=unmute_reason)

    try:
        result = _create_github_issue(
            config,
            title=title,
            body=body,
        )

        _store_success_info(service_config_id)
        logger.info(f"GitHub issue created for Bugsink issue {issue_id}: #{result.get('number')}")

    except HTTPError as e:
        response_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"GitHub API error: {e.code} - {response_body}")

        class ResponseWrapper:
            def __init__(self, code, text):
                self.code = code
                self.status = code
                self.text = text

        _store_failure_info(service_config_id, e, ResponseWrapper(e.code, response_body))

    except URLError as e:
        logger.error(f"GitHub connection error: {e.reason}")
        _store_failure_info(service_config_id, e)

    except Exception as e:
        logger.exception(f"Unexpected error sending to GitHub: {e}")
        _store_failure_info(service_config_id, e)


class GitHubIssuesBackend:
    """Backend class for GitHub Issues integration.

    Compatible with Bugsink v2 backend interface.
    """

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        """Return the configuration form class."""
        return GitHubIssuesConfigForm

    def send_test_message(self):
        """Dispatch test message task."""
        config = json.loads(self.service_config.config)
        github_issues_send_test_message.delay(
            config["repository"],
            config["access_token"],
            config.get("labels", []),
            config.get("assignees", []),
            self.service_config.project.name,
            self.service_config.display_name,
            self.service_config.id,
        )

    def send_alert(self, issue_id, state_description, alert_article, alert_reason, **kwargs):
        """Dispatch alert task."""
        from bugsink.app_settings import get_settings
        config = json.loads(self.service_config.config)

        # Check if we should only create issues for NEW errors
        if config.get("only_new_issues", True) and state_description != "NEW":
            logger.debug(f"Skipping GitHub issue for {state_description} issue {issue_id} (only_new_issues=True)")
            return

        # Get base URL from Bugsink settings (same as Slack backend)
        bugsink_base_url = get_settings().BASE_URL

        github_issues_send_alert.delay(
            config["repository"],
            config["access_token"],
            config.get("labels", []),
            config.get("assignees", []),
            issue_id,
            state_description,
            alert_article,
            alert_reason,
            self.service_config.id,
            bugsink_base_url=bugsink_base_url,
            **kwargs,
        )
