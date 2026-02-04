# Extended Notification Backends for Bugsink

This document describes the additional notification backends contributed to Bugsink, enabling integration with enterprise issue tracking systems, incident management platforms, and generic webhook endpoints.

## Overview

This contribution adds **5 new notification backends** to Bugsink's alert system:

| Backend | Service | Use Case |
|---------|---------|----------|
| `jira_cloud` | Jira Cloud | Automatic bug ticket creation in Atlassian Jira |
| `github_issues` | GitHub Issues | Automatic issue creation in GitHub repositories |
| `microsoft_teams` | Microsoft Teams | Alert notifications via Teams webhooks |
| `pagerduty` | PagerDuty | Incident management and on-call alerting |
| `webhook` | Generic Webhook | Custom integrations via HTTP endpoints |

## Architecture

All backends follow Bugsink's existing backend architecture pattern:

```
alerts/service_backends/
├── __init__.py
├── slack.py           # Existing
├── mattermost.py      # Existing
├── discord.py         # Existing
├── jira_cloud.py      # NEW
├── github_issues.py   # NEW
├── microsoft_teams.py # NEW
├── pagerduty.py       # NEW
└── webhook.py         # NEW
```

Each backend provides:
- A `ConfigForm` class (Django Form) for user configuration
- A `Backend` class implementing `send_test_message()` and `send_alert()`
- Async task functions using `@shared_task` for non-blocking message delivery
- Failure tracking integration with `MessagingServiceConfig`

## Backend Details

### 1. Jira Cloud (`jira_cloud`)

Creates bug tickets in Jira Cloud when Bugsink detects issues.

**Configuration Fields:**
- `jira_url` - Jira Cloud URL (e.g., `https://your-domain.atlassian.net`)
- `user_email` - Email associated with the API token
- `api_token` - Jira API token ([create here](https://id.atlassian.com/manage-profile/security/api-tokens))
- `project_key` - Target project key (e.g., `BUG`, `PROJ`)
- `issue_type` - Issue type to create (Bug, Task, Story, etc.)
- `labels` - Comma-separated labels to apply
- `only_new_issues` - Create tickets only for NEW issues (prevents duplicates)

**Features:**
- Uses Atlassian Document Format (ADF) for rich descriptions
- Includes direct links to Bugsink issues
- Supports all standard Jira issue types
- Deduplication option to avoid ticket spam

**Setup:**

1. Go to [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click "Create API token"
3. Give it a label (e.g., "Bugsink Integration")
4. Copy the generated token (you won't see it again)
5. Use your Atlassian account email as the "User Email" in Bugsink

### 2. GitHub Issues (`github_issues`)

Creates issues in GitHub repositories when errors occur.

**Configuration Fields:**
- `repository` - Repository in `owner/repo` format
- `access_token` - GitHub Personal Access Token with `issues:write` scope
- `labels` - Comma-separated labels (e.g., `bug,production`)
- `assignees` - Comma-separated GitHub usernames to assign
- `only_new_issues` - Create issues only for NEW errors

**Features:**
- GitHub-flavored Markdown formatting
- Automatic label and assignee assignment
- Direct links to Bugsink issues
- Works with both classic and fine-grained tokens

**Setup (Classic Token):**

1. Go to [GitHub Personal Access Tokens](https://github.com/settings/tokens)
2. Click "Generate new token (classic)"
3. Select scope: `repo` (for private repos) or `public_repo` (for public repos)
4. Generate and copy the token

**Setup (Fine-grained Token - Recommended):**

1. Go to [GitHub Fine-grained Tokens](https://github.com/settings/tokens?type=beta)
2. Click "Generate new token"
3. Select the target repository
4. Under "Repository permissions", set "Issues" to "Read and write"
5. Generate and copy the token

### 3. Microsoft Teams (`microsoft_teams`)

Sends alerts to Microsoft Teams channels via webhooks.

**Configuration Fields:**
- `webhook_url` - Teams Webhook URL (Workflows or legacy connector)
- `channel_name` - Display name for reference (optional)
- `mention_users` - Comma-separated emails to @mention
- `theme_color` - Hex color for card accent

**Features:**
- Adaptive Cards for rich formatting
- @mention support for team members
- "View in Bugsink" action button
- Supports both new Workflows webhooks and legacy connectors

**Setup Method 1 - Workflows (Recommended):**

1. Open the Teams channel where you want alerts
2. Click the "..." menu > "Workflows"
3. Search for "Post to a channel when a webhook request is received"
4. Configure the workflow and copy the webhook URL
5. URL format: `https://xxx.webhook.office.com/webhookb2/...`

**Setup Method 2 - Legacy Incoming Webhook (deprecated):**

1. Go to Channel Settings > Connectors > Incoming Webhook
2. Configure and copy the webhook URL
3. URL format: `https://outlook.office.com/webhook/...`

> **Warning:** Microsoft is retiring legacy Office 365 Connectors by March 2026. Migrate to Workflows for continued support.

### 4. PagerDuty (`pagerduty`)

Creates incidents in PagerDuty for on-call alerting.

**Configuration Fields:**
- `routing_key` - PagerDuty Events API v2 Integration Key (32 chars)
- `default_severity` - Incident severity (critical, error, warning, info)
- `service_name` - Custom source name (defaults to "Bugsink")
- `include_link` - Include link to Bugsink issue

**Features:**
- Events API v2 integration
- Automatic incident deduplication by issue ID
- Configurable severity levels
- Custom details with full error context

**Setup:**

1. Log in to your PagerDuty account
2. Go to Services > Select your service (or create a new one)
3. Navigate to: Integrations > Add Integration
4. Select "Events API v2"
5. Copy the 32-character Integration Key (also called Routing Key)

### 5. Generic Webhook (`webhook`)

Sends alerts to any HTTP endpoint as JSON payloads.

**Configuration Fields:**
- `webhook_url` - Target HTTP(S) endpoint
- `http_method` - POST, PUT, or PATCH
- `secret_header` - Header name for authentication (optional)
- `secret_value` - Secret value for the header
- `custom_headers` - Additional headers as JSON
- `include_full_payload` - Include all available issue details

**Features:**
- Flexible HTTP method selection
- Custom authentication headers
- Arbitrary custom headers via JSON
- Full or minimal payload options

**Payload Structure:**
```json
{
  "event_type": "alert",
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "bugsink",
  "data": {
    "issue_id": "123",
    "issue_url": "https://bugsink.example.com/issues/issue/123/event/last/",
    "summary": "[NEW] ValueError: Invalid input",
    "error_type": "ValueError",
    "error_message": "Invalid input",
    "project": "My Project",
    "first_seen": "2024-01-15T10:00:00Z",
    "last_seen": "2024-01-15T10:30:00Z",
    "event_count": 5,
    "alert_type": "NEW",
    "alert_reason": "new"
  }
}
```

## Implementation Notes

### HTTP Client

The new backends use the `requests` library, consistent with Bugsink's existing backends (slack.py, mattermost.py, discord.py). This ensures:

- Consistency across all notification backends
- Uses the same error handling patterns (`requests.RequestException`)
- Provides consistent timeout handling (30 seconds)

### Error Handling

All backends implement comprehensive error handling:
- HTTP errors are captured with status codes and response bodies
- Connection errors are logged with detailed messages
- Failure information is stored in `MessagingServiceConfig` for UI display
- Success clears previous failure status

### Async Task Execution

All message sending is performed asynchronously using Snappea's `@shared_task` decorator:
- Non-blocking alert delivery
- Automatic retry handling (when configured)
- Proper database transaction management via `immediate_atomic`

### Security Considerations

- API tokens and secrets are stored in the encrypted `config` field
- Webhook URLs support HTTPS
- Password fields use `render_value=True` to allow editing without re-entering
- No sensitive data is logged

## Testing

Each backend provides a `send_test_message()` method that:
1. Sends a clearly marked test message/ticket
2. Uses minimal severity where applicable (e.g., `info` for PagerDuty)
3. Updates failure tracking on error
4. Clears failure status on success

## Files Changed

```
alerts/models.py                              # Backend registration
alerts/service_backends/jira_cloud.py         # NEW: Jira Cloud backend
alerts/service_backends/github_issues.py      # NEW: GitHub Issues backend
alerts/service_backends/microsoft_teams.py    # NEW: Microsoft Teams backend
alerts/service_backends/pagerduty.py          # NEW: PagerDuty backend
alerts/service_backends/webhook.py            # NEW: Generic Webhook backend
```

## Compatibility

- **Bugsink Version:** 2.x
- **Python Version:** 3.10+
- **Django Version:** Compatible with Bugsink's Django version
- **No additional dependencies required**

## Contributing

This contribution was developed by [BAUER GROUP](https://bauer-group.com).

---

*For questions or issues, please open a GitHub issue or contact the maintainers.*
