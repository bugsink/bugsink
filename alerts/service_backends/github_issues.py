"""
Bugsink Messaging Backend: GitHub Issues
=========================================

Creates issues in a GitHub repository when errors occur in Bugsink.

Requirements:
    - GitHub repository with Issues enabled
    - Personal Access Token with 'issues:write' scope

Setup (Classic Token):
    1. Go to: https://github.com/settings/tokens
    2. Click "Generate new token (classic)"
    3. Select scope: "repo" (for private repos) or "public_repo" (for public repos)
    4. Generate and copy the token

Setup (Fine-grained Token - Recommended):
    1. Go to: https://github.com/settings/tokens?type=beta
    2. Click "Generate new token"
    3. Select the repository
    4. Under "Repository permissions", set "Issues" to "Read and write"
    5. Generate and copy the token
"""

import json
import requests

from django import forms
from django.utils import timezone

from snappea.decorators import shared_task
from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic

from issues.models import Issue


GITHUB_API_URL = "https://api.github.com"


class GitHubIssuesConfigForm(forms.Form):
    """Configuration form for GitHub Issues integration."""

    repository = forms.CharField(
        label="Repository",
        help_text="Repository in 'owner/repo' format, e.g., 'myorg/myproject'",
        max_length=200,
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
        required=False,
    )
    assignees = forms.CharField(
        label="Assignees (optional)",
        help_text="Comma-separated GitHub usernames to assign, e.g., 'user1,user2'",
        required=False,
    )
    only_new_issues = forms.BooleanField(
        label="Only New Issues",
        help_text="Create issues only for NEW errors (recommended to avoid duplicates).",
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
            self.fields["repository"].initial = config.get("repository", "")
            self.fields["access_token"].initial = config.get("access_token", "")
            self.fields["labels"].initial = ",".join(config.get("labels", []))
            self.fields["assignees"].initial = ",".join(config.get("assignees", []))
            self.fields["only_new_issues"].initial = config.get("only_new_issues", True)

    def clean_repository(self):
        repo = self.cleaned_data["repository"].strip()
        if "/" not in repo or repo.count("/") != 1:
            raise forms.ValidationError("Repository must be in 'owner/repo' format")
        owner, name = repo.split("/")
        if not owner or not name:
            raise forms.ValidationError("Both owner and repository name are required")
        return repo

    def get_config(self):
        return {
            "repository": self.cleaned_data["repository"],
            "access_token": self.cleaned_data["access_token"],
            "labels": [l.strip() for l in self.cleaned_data.get("labels", "").split(",") if l.strip()],
            "assignees": [a.strip() for a in self.cleaned_data.get("assignees", "").split(",") if a.strip()],
            "only_new_issues": self.cleaned_data.get("only_new_issues", True),
        }


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
def github_issues_send_test_message(repository, access_token, labels, assignees,
                                     project_name, display_name, service_config_id):
    """Send a test issue to verify GitHub configuration."""
    url = f"{GITHUB_API_URL}/repos/{repository}/issues"

    payload = {
        "title": f"[Bugsink] Test Issue - {project_name}"[:256],
        "body": (
            "## Test Issue\n\n"
            f"This is a test issue created by **Bugsink** to verify the GitHub integration.\n\n"
            f"- **Project:** {project_name}\n"
            f"- **Service:** {display_name}\n\n"
            "If you see this issue, your configuration is working correctly.\n\n"
            "You can safely close and delete this issue.\n\n"
            "---\n"
            "*Automatically created by [Bugsink](https://bugsink.com)*"
        ),
    }

    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees

    try:
        result = requests.post(
            url,
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
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
def github_issues_send_alert(repository, access_token, labels, assignees,
                              issue_id, state_description, alert_article, alert_reason,
                              service_config_id, unmute_reason=None):
    """Create a GitHub issue for a Bugsink alert."""
    issue = Issue.objects.get(id=issue_id)
    issue_url = get_settings().BASE_URL + issue.get_absolute_url()

    title = f"[{state_description}] {issue.calculated_type or 'Error'}: {issue.calculated_value or 'Unknown'}"

    body = f"""## Error Details

**Error Type:** `{issue.calculated_type or 'Unknown'}`
**Error Message:** {issue.calculated_value or 'No message'}

**View in Bugsink:** [{issue_url}]({issue_url})

## Timeline

| First Seen | Last Seen | Event Count |
|------------|-----------|-------------|
| {issue.first_seen.isoformat() if issue.first_seen else 'Unknown'} | \
{issue.last_seen.isoformat() if issue.last_seen else 'Unknown'} | {issue.digested_event_count} |

## Context

- **Project:** {issue.project.name}
- **Alert Type:** {state_description}
- **Reason:** {alert_reason}
"""

    if unmute_reason:
        body += f"- **Unmute Reason:** {unmute_reason}\n"

    body += "\n---\n*This issue was automatically created by [Bugsink](https://bugsink.com)*"

    url = f"{GITHUB_API_URL}/repos/{repository}/issues"

    payload = {
        "title": title[:256],
        "body": body,
    }

    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees

    try:
        result = requests.post(
            url,
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
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


class GitHubIssuesBackend:
    """Backend class for GitHub Issues integration."""

    def __init__(self, service_config):
        self.service_config = service_config

    @classmethod
    def get_form_class(cls):
        return GitHubIssuesConfigForm

    def send_test_message(self):
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
        config = json.loads(self.service_config.config)

        if config.get("only_new_issues", True) and state_description != "NEW":
            return

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
            **kwargs,
        )
