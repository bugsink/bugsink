from django.test import TestCase as DjangoTestCase
from unittest.mock import patch, Mock
import json
import requests

from django.core import mail
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.utils import timezone

from issues.factories import get_or_create_issue
from projects.models import Project, ProjectMembership
from events.factories import create_event
from teams.models import Team, TeamMembership

from .models import MessagingServiceConfig
from .service_backends.slack import slack_backend_send_test_message, slack_backend_send_alert
from .service_backends.discord import discord_backend_send_test_message, discord_backend_send_alert
from .tasks import send_new_issue_alert, send_regression_alert, send_unmute_alert, _get_users_for_email_alert
from .views import DEBUG_CONTEXTS

User = get_user_model()


class TestAlertSending(DjangoTestCase):

    def test_send_new_issue_alert(self):
        project = Project.objects.create(name="Test project")

        user = User.objects.create_user(username="testuser", email="test@example.org")
        ProjectMembership.objects.create(
            project=project,
            user=user,
            send_email_alerts=True,
        )

        issue, _ = get_or_create_issue(project=project)
        create_event(project=project, issue=issue)

        send_new_issue_alert(issue.id)

        self.assertEqual(len(mail.outbox), 1)

    def test_send_regression_alert(self):
        project = Project.objects.create(name="Test project")

        user = User.objects.create_user(username="testuser", email="test@example.org")
        ProjectMembership.objects.create(
            project=project,
            user=user,
            send_email_alerts=True,
        )

        issue, _ = get_or_create_issue(project=project)
        create_event(project=project, issue=issue)

        send_regression_alert(issue.id)

        self.assertEqual(len(mail.outbox), 1)

    def test_send_unmute_alert(self):
        project = Project.objects.create(name="Test project")

        user = User.objects.create_user(username="testuser", email="test@example.org")
        ProjectMembership.objects.create(
            project=project,
            user=user,
            send_email_alerts=True,
        )

        issue, _ = get_or_create_issue(project=project)
        create_event(project=project, issue=issue)

        send_unmute_alert(issue.id, "Some unumte reason")

        self.assertEqual(len(mail.outbox), 1)

    def test_txt_and_html_have_relevant_variables_defined(self):
        example_context = DEBUG_CONTEXTS["issue_alert"]
        html_template = get_template("mails/issue_alert.html")
        text_template = get_template("mails/issue_alert.txt")

        unused_in_text = [
            "base_url",  # link to the site is not included at the top of the text template
        ]

        for type_, template in [("html", html_template), ("text", text_template)]:
            for variable in example_context.keys():
                if type_ == "text" and variable in unused_in_text:
                    continue

                self.assertTrue(
                    "{{ %s" % variable in template.template.source, "'{{ %s ' not in %s template" % (variable, type_))

    def test_get_users_for_email_alert(self):
        team = Team.objects.create(name="Test team")
        project = Project.objects.create(name="Test project", team=team)
        user = User.objects.create_user(username="testuser", email="test@example.org", send_email_alerts=True)
        issue, _ = get_or_create_issue(project=project)

        # no ProjectMembership, user should not be included
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # ProjectMembership w/ send=False, should not be included
        pm = ProjectMembership.objects.create(project=project, user=user, send_email_alerts=False)
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # ProjectMembership w/ send=True, should be included
        pm.send_email_alerts = True
        pm.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [user])

        # Set send=None, fall back to User (which has True)
        pm.send_email_alerts = None
        pm.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [user])

        # (User has False)
        user.send_email_alerts = False
        user.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # Insert TeamMembership - this provides an intermediate layer of configuration between User and
        # ProjectMembership; we start with send=True at the tm level and expect the user to be included
        tm = TeamMembership.objects.create(team=team, user=user, send_email_alerts=True)
        self.assertEqual(list(_get_users_for_email_alert(issue)), [user])

        # Set send=False at the tm level, user should not be included
        tm.send_email_alerts = False
        tm.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # Set send=None at the tm level, back to the user level (which is False)
        tm.send_email_alerts = None
        tm.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # Set send=True at the user level, user should be included
        user.send_email_alerts = True
        user.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [user])


class TestSlackBackendErrorHandling(DjangoTestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Test project")
        self.config = MessagingServiceConfig.objects.create(
            project=self.project,
            display_name="Test Slack",
            kind="slack",
            config=json.dumps({"webhook_url": "https://hooks.slack.com/test"}),
        )

    @patch('alerts.service_backends.slack.requests.post')
    def test_slack_test_message_success_clears_failure_status(self, mock_post):
        # Set up existing failure status
        self.config.last_failure_timestamp = timezone.now()
        self.config.last_failure_status_code = 500
        self.config.last_failure_response_text = "Server Error"
        self.config.save()

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Send test message
        slack_backend_send_test_message(
            "https://hooks.slack.com/test",
            "Test project",
            "Test Slack",
            self.config.id
        )

        # Verify failure status was cleared
        self.config.refresh_from_db()
        self.assertIsNone(self.config.last_failure_timestamp)
        self.assertIsNone(self.config.last_failure_status_code)
        self.assertIsNone(self.config.last_failure_response_text)

    @patch('alerts.service_backends.slack.requests.post')
    def test_slack_test_message_http_error_stores_failure(self, mock_post):
        # Mock HTTP error response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = '{"error": "webhook_not_found"}'

        # Create the HTTPError with response attached
        http_error = requests.HTTPError()
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        mock_post.return_value = mock_response

        # Send test message
        slack_backend_send_test_message(
            "https://hooks.slack.com/test",
            "Test project",
            "Test Slack",
            self.config.id
        )

        # Verify failure status was stored
        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_failure_timestamp)
        self.assertEqual(self.config.last_failure_status_code, 404)
        self.assertEqual(self.config.last_failure_response_text, '{"error": "webhook_not_found"}')
        self.assertTrue(self.config.last_failure_is_json)
        self.assertEqual(self.config.last_failure_error_type, "HTTPError")

    @patch('alerts.service_backends.slack.requests.post')
    def test_slack_test_message_non_json_error_stores_failure(self, mock_post):
        # Mock HTTP error response with non-JSON text
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'

        # Create the HTTPError with response attached
        http_error = requests.HTTPError()
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        mock_post.return_value = mock_response

        # Send test message and expect it to raise
        slack_backend_send_test_message(
            "https://hooks.slack.com/test",
            "Test project",
            "Test Slack",
            self.config.id
        )

        # Verify failure status was stored
        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_failure_timestamp)
        self.assertEqual(self.config.last_failure_status_code, 500)
        self.assertEqual(self.config.last_failure_response_text, 'Internal Server Error')
        self.assertFalse(self.config.last_failure_is_json)

    @patch('alerts.service_backends.slack.requests.post')
    def test_slack_test_message_connection_error_stores_failure(self, mock_post):
        # Mock connection error
        mock_post.side_effect = requests.ConnectionError("Connection failed")

        # Send test message
        slack_backend_send_test_message(
            "https://hooks.slack.com/test",
            "Test project",
            "Test Slack",
            self.config.id
        )

        # Verify failure status was stored
        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_failure_timestamp)
        self.assertIsNone(self.config.last_failure_status_code)  # No HTTP response
        self.assertIsNone(self.config.last_failure_response_text)
        self.assertIsNone(self.config.last_failure_is_json)
        self.assertEqual(self.config.last_failure_error_type, "ConnectionError")
        self.assertEqual(self.config.last_failure_error_message, "Connection failed")

    @patch('alerts.service_backends.slack.requests.post')
    def test_slack_alert_message_success_clears_failure_status(self, mock_post):
        # Set up existing failure status
        self.config.last_failure_timestamp = timezone.now()
        self.config.last_failure_status_code = 500
        self.config.save()

        # Create issue
        issue, _ = get_or_create_issue(project=self.project)

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Send alert message
        slack_backend_send_alert(
            "https://hooks.slack.com/test",
            issue.id,
            "New issue",
            "a",
            "NEW",
            self.config.id
        )

        # Verify failure status was cleared
        self.config.refresh_from_db()
        self.assertIsNone(self.config.last_failure_timestamp)

    def test_has_recent_failure_method(self):
        # Initially no failure
        self.assertFalse(self.config.has_recent_failure())

        # Set failure
        self.config.last_failure_timestamp = timezone.now()
        self.config.save()
        self.assertTrue(self.config.has_recent_failure())

        # Clear failure
        self.config.clear_failure_status()
        self.config.save()
        self.assertFalse(self.config.has_recent_failure())


class TestDiscordBackendErrorHandling(DjangoTestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Test project")
        self.config = MessagingServiceConfig.objects.create(
            project=self.project,
            display_name="Test Discord",
            kind="discord",
            config=json.dumps({"webhook_url": "https://discord.com/api/webhooks/test"}),
        )

    @patch('alerts.service_backends.discord.requests.post')
    def test_discord_test_message_success_clears_failure_status(self, mock_post):
        # Set up existing failure status
        self.config.last_failure_timestamp = timezone.now()
        self.config.last_failure_status_code = 500
        self.config.last_failure_response_text = "Server Error"
        self.config.save()

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Send test message
        discord_backend_send_test_message(
            "https://discord.com/api/webhooks/test",
            "Test project",
            "Test Discord",
            self.config.id
        )

        # Verify failure status was cleared
        self.config.refresh_from_db()
        self.assertIsNone(self.config.last_failure_timestamp)
        self.assertIsNone(self.config.last_failure_status_code)
        self.assertIsNone(self.config.last_failure_response_text)

    @patch('alerts.service_backends.discord.requests.post')
    def test_discord_test_message_http_error_stores_failure(self, mock_post):
        # Mock HTTP error response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = '{"message": "Unknown Webhook", "code": 10015}'

        # Create the HTTPError with response attached
        http_error = requests.HTTPError()
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        mock_post.return_value = mock_response

        # Send test message
        discord_backend_send_test_message(
            "https://discord.com/api/webhooks/test",
            "Test project",
            "Test Discord",
            self.config.id
        )

        # Verify failure status was stored
        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_failure_timestamp)
        self.assertEqual(self.config.last_failure_status_code, 404)
        self.assertEqual(self.config.last_failure_response_text, '{"message": "Unknown Webhook", "code": 10015}')
        self.assertTrue(self.config.last_failure_is_json)
        self.assertEqual(self.config.last_failure_error_type, "HTTPError")

    @patch('alerts.service_backends.discord.requests.post')
    def test_discord_test_message_non_json_error_stores_failure(self, mock_post):
        # Mock HTTP error response with non-JSON text
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'

        # Create the HTTPError with response attached
        http_error = requests.HTTPError()
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        mock_post.return_value = mock_response

        # Send test message
        discord_backend_send_test_message(
            "https://discord.com/api/webhooks/test",
            "Test project",
            "Test Discord",
            self.config.id
        )

        # Verify failure status was stored
        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_failure_timestamp)
        self.assertEqual(self.config.last_failure_status_code, 500)
        self.assertEqual(self.config.last_failure_response_text, 'Internal Server Error')
        self.assertFalse(self.config.last_failure_is_json)

    @patch('alerts.service_backends.discord.requests.post')
    def test_discord_test_message_connection_error_stores_failure(self, mock_post):
        # Mock connection error
        mock_post.side_effect = requests.ConnectionError("Connection failed")

        # Send test message
        discord_backend_send_test_message(
            "https://discord.com/api/webhooks/test",
            "Test project",
            "Test Discord",
            self.config.id
        )

        # Verify failure status was stored
        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_failure_timestamp)
        self.assertIsNone(self.config.last_failure_status_code)  # No HTTP response
        self.assertIsNone(self.config.last_failure_response_text)
        self.assertIsNone(self.config.last_failure_is_json)
        self.assertEqual(self.config.last_failure_error_type, "ConnectionError")
        self.assertEqual(self.config.last_failure_error_message, "Connection failed")

    @patch('alerts.service_backends.discord.requests.post')
    def test_discord_alert_message_success_clears_failure_status(self, mock_post):
        # Set up existing failure status
        self.config.last_failure_timestamp = timezone.now()
        self.config.last_failure_status_code = 500
        self.config.save()

        # Create issue
        issue, _ = get_or_create_issue(project=self.project)

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Send alert message
        discord_backend_send_alert(
            "https://discord.com/api/webhooks/test",
            issue.id,
            "New issue",
            "a",
            "NEW",
            self.config.id
        )

        # Verify failure status was cleared
        self.config.refresh_from_db()
        self.assertIsNone(self.config.last_failure_timestamp)

    def test_has_recent_failure_method(self):
        # Initially no failure
        self.assertFalse(self.config.has_recent_failure())

        # Set failure
        self.config.last_failure_timestamp = timezone.now()
        self.config.save()
        self.assertTrue(self.config.has_recent_failure())

        # Clear failure
        self.config.clear_failure_status()
        self.config.save()
        self.assertFalse(self.config.has_recent_failure())
