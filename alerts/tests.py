from django.test import TestCase as DjangoTestCase
from unittest.mock import patch, Mock
import json
import requests
from socket import gaierror

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
from .service_backends.webhook import webhook_backend_send_test_message, webhook_backend_send_alert
from .service_backends.discord import DiscordConfigForm
from .service_backends.mattermost import MattermostConfigForm
from .service_backends.slack import SlackConfigForm
from .service_backends.webhook import GenericWebhookConfigForm
from .service_backends.webhook_security import validate_webhook_url
from .tasks import send_new_issue_alert, send_regression_alert, send_unmute_alert, _get_users_for_email_alert
from .views import DEBUG_CONTEXTS
from bugsink.app_settings import override_settings as override_bugsink_settings

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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.requests.post')
    def test_slack_test_message_blocked_target_stores_failure_without_network_call(self, mock_post):
        slack_backend_send_test_message(
            "http://10.0.0.42/hooks/test",
            "Test project",
            "Test Slack",
            self.config.id,
        )

        mock_post.assert_not_called()
        self.config.refresh_from_db()
        self.assertEqual(self.config.last_failure_error_type, "ValueError")
        self.assertIn("non-global IP address", self.config.last_failure_error_message)

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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
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


class TestWebhookSecurityValidation(DjangoTestCase):
    def test_rejects_private_ip_target(self):
        with override_bugsink_settings(ALERTS_WEBHOOK_OUTBOUND_MODE="open"):
            with self.assertRaisesRegex(ValueError, "non-global IP address"):
                validate_webhook_url("http://10.0.0.42/hooks/example")

    def test_rejects_ipv4_mapped_ipv6_loopback_target(self):
        with override_bugsink_settings(ALERTS_WEBHOOK_OUTBOUND_MODE="open"):
            with self.assertRaisesRegex(ValueError, "non-global IP address"):
                validate_webhook_url("http://[::ffff:127.0.0.1]/hooks/example")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_rejects_hostname_that_resolves_to_private_ip(self, mock_resolve):
        mock_resolve.return_value = {"10.1.2.3"}
        with override_bugsink_settings(ALERTS_WEBHOOK_OUTBOUND_MODE="open"):
            with self.assertRaisesRegex(ValueError, "non-global IP address"):
                validate_webhook_url("https://webhook.internal.example/hooks/example")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_allowlist_only_denies_non_allowlisted_target(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        with override_bugsink_settings(ALERTS_WEBHOOK_OUTBOUND_MODE="allowlist_only"):
            with self.assertRaisesRegex(ValueError, "not allowlisted"):
                validate_webhook_url("https://hooks.example.com/webhook")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_allowlist_only_allows_allowlisted_hostname(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        with override_bugsink_settings(
                ALERTS_WEBHOOK_OUTBOUND_MODE="allowlist_only",
                ALERTS_WEBHOOK_ALLOW_LIST=["hooks.example.com"]):
            validate_webhook_url("https://hooks.example.com/webhook")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_allows_public_ip_target_in_open_mode(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        validate_webhook_url("https://hooks.example.com/webhook")

    @patch("alerts.service_backends.webhook_security._validate_raw_url_characters")
    def test_rejects_backslash_exploit_that_tries_to_bypass_allowlist(self, mock_validate_raw_characters):
        # We can't think of an exploit that would exploit discrepancies between requests' parser and other parsers but
        # not already be caught by our raw character validation. Hence we need to turn off raw character validation in
        # the test to test against the case of mismatch-exploiting that we do know to exist.
        mock_validate_raw_characters.return_value = None

        with override_bugsink_settings(
                ALERTS_WEBHOOK_OUTBOUND_MODE="allowlist_only",
                ALERTS_WEBHOOK_ALLOW_LIST=["whitelist.com"]):
            with self.assertRaisesRegex(ValueError, "not allowlisted"):
                validate_webhook_url(r"http://127.0.0.1:6666\@whitelist.com")

    def test_rejects_raw_unicode_character(self):
        with self.assertRaisesRegex(ValueError, "must contain only ASCII URL characters"):
            validate_webhook_url("https://hooks.example.com/caf\xe9")

    def test_rejects_raw_backslash_character(self):
        with self.assertRaisesRegex(ValueError, "must contain only ASCII URL characters"):
            validate_webhook_url(r"https://hooks.example.com\path")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_denied_when_allow_and_deny_both_match(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        with override_bugsink_settings(
                ALERTS_WEBHOOK_ALLOW_LIST=["hooks.example.com"],
                ALERTS_WEBHOOK_DENY_LIST=["hooks.example.com"]):
            with self.assertRaisesRegex(ValueError, "matches ALERTS_WEBHOOK_DENY_LIST"):
                validate_webhook_url("https://hooks.example.com/webhook")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_allow_cidr_matches_resolved_ip(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        with override_bugsink_settings(
                ALERTS_WEBHOOK_OUTBOUND_MODE="allowlist_only",
                ALERTS_WEBHOOK_ALLOW_LIST=["93.184.216.0/24"]):
            validate_webhook_url("https://hooks.example.com/webhook")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_deny_cidr_matches_resolved_ip(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        with override_bugsink_settings(
                ALERTS_WEBHOOK_DENY_LIST=["93.184.216.0/24"]):
            with self.assertRaisesRegex(ValueError, "matches ALERTS_WEBHOOK_DENY_LIST"):
                validate_webhook_url("https://hooks.example.com/webhook")

    def test_non_global_can_be_allowed_when_toggle_disabled(self):
        with override_bugsink_settings(
                ALERTS_WEBHOOK_OUTBOUND_MODE="open",
                ALERTS_WEBHOOK_DENY_NON_GLOBAL=False):
            validate_webhook_url("http://10.0.0.42/hooks/example")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_rejects_invalid_cidr_in_allow_list(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        with override_bugsink_settings(ALERTS_WEBHOOK_ALLOW_LIST=["93.184.216.0/33"]):
            with self.assertRaisesRegex(ValueError, "Invalid entry in ALERTS_WEBHOOK_ALLOW_LIST"):
                validate_webhook_url("https://hooks.example.com/webhook")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_rejects_invalid_cidr_in_deny_list(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        with override_bugsink_settings(ALERTS_WEBHOOK_DENY_LIST=["93.184.216.0/33"]):
            with self.assertRaisesRegex(ValueError, "Invalid entry in ALERTS_WEBHOOK_DENY_LIST"):
                validate_webhook_url("https://hooks.example.com/webhook")

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_rejects_unresolvable_hostname(self, mock_resolve):
        mock_resolve.side_effect = gaierror("Name or service not known")
        with self.assertRaisesRegex(ValueError, "could not be resolved"):
            validate_webhook_url("https://hooks.example.com/webhook")


class TestWebhookConfigForms(DjangoTestCase):
    def test_slack_form_rejects_blocked_target(self):
        form = SlackConfigForm(data={"webhook_url": "http://10.0.0.42/hooks/test"})

        self.assertFalse(form.is_valid())
        self.assertIn("non-global IP address", form.errors["webhook_url"][0])

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_discord_form_accepts_public_target(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        form = DiscordConfigForm(data={"webhook_url": "https://discord.com/api/webhooks/test"})

        self.assertTrue(form.is_valid())

    def test_mattermost_form_rejects_blocked_target(self):
        form = MattermostConfigForm(data={"webhook_url": "http://10.0.0.42/hooks/test", "channel": "town-square"})

        self.assertFalse(form.is_valid())
        self.assertIn("non-global IP address", form.errors["webhook_url"][0])

    def test_webhook_form_rejects_blocked_target(self):
        form = GenericWebhookConfigForm(data={"webhook_url": "http://10.0.0.42/hooks/test"})

        self.assertFalse(form.is_valid())
        self.assertIn("non-global IP address", form.errors["webhook_url"][0])

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_webhook_form_accepts_public_target(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        form = GenericWebhookConfigForm(data={"webhook_url": "https://hooks.example.com/webhook"})

        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.get_config(),
            {"webhook_url": "https://hooks.example.com/webhook", "body_template": ""},
        )

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_webhook_form_config_includes_body_template(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        form = GenericWebhookConfigForm(data={
            "webhook_url": "https://hooks.example.com/webhook",
            "body_template": '{"text": $summary}',
        })

        self.assertTrue(form.is_valid())
        self.assertEqual(form.get_config(), {
            "webhook_url": "https://hooks.example.com/webhook",
            "body_template": '{"text": $summary}',
        })

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_webhook_form_prefills_body_template_from_config(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        form = GenericWebhookConfigForm(config={
            "webhook_url": "https://hooks.example.com/webhook",
            "body_template": '{"text": $summary}',
        })

        self.assertEqual(form.fields["body_template"].initial, '{"text": $summary}')

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_webhook_form_accepts_valid_template(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        form = GenericWebhookConfigForm(data={
            "webhook_url": "https://hooks.example.com/webhook",
            "body_template": '{"text": $summary, "id": $issue_friendly_id}',
        })

        self.assertTrue(form.is_valid())

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_webhook_form_rejects_typoed_placeholder(self, mock_resolve):
        # $summry is a typo: left literal by safe_substitute, so a bareword json.loads rejects.
        mock_resolve.return_value = {"93.184.216.34"}
        form = GenericWebhookConfigForm(data={
            "webhook_url": "https://hooks.example.com/webhook",
            "body_template": '{"text": $summry}',
        })

        self.assertFalse(form.is_valid())
        self.assertIn("valid JSON", form.errors["body_template"][0])

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_webhook_form_rejects_quoted_placeholder(self, mock_resolve):
        # placeholders already expand to JSON-encoded values; wrapping in quotes yields ""..."".
        mock_resolve.return_value = {"93.184.216.34"}
        form = GenericWebhookConfigForm(data={
            "webhook_url": "https://hooks.example.com/webhook",
            "body_template": '{"text": "$summary"}',
        })

        self.assertFalse(form.is_valid())
        self.assertIn("valid JSON", form.errors["body_template"][0])

    @patch("alerts.service_backends.webhook_security._resolve_ip_addresses")
    def test_webhook_form_rejects_whitespace_only_template(self, mock_resolve):
        mock_resolve.return_value = {"93.184.216.34"}
        form = GenericWebhookConfigForm(data={
            "webhook_url": "https://hooks.example.com/webhook",
            "body_template": "   ",
        })

        self.assertFalse(form.is_valid())
        self.assertIn("valid JSON", form.errors["body_template"][0])


class TestGenericWebhookBackend(DjangoTestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Test project")
        self.config = MessagingServiceConfig.objects.create(
            project=self.project,
            display_name="Test Webhook",
            kind="webhook",
            config=json.dumps({"webhook_url": "https://hooks.example.com/webhook"}),
        )

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_test_message_success_clears_failure_status(self, mock_post):
        self.config.last_failure_timestamp = timezone.now()
        self.config.last_failure_status_code = 500
        self.config.save()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_test_message(
            "https://hooks.example.com/webhook",
            "Test project",
            "Test Webhook",
            self.config.id,
        )

        self.config.refresh_from_db()
        self.assertIsNone(self.config.last_failure_timestamp)

        # payload shape: human-readable text + issue=None for test messages
        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIn("Test message", sent["text"])
        self.assertIsNone(sent["issue"])

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_alert_message_payload_shape(self, mock_post):
        issue, _ = get_or_create_issue(project=self.project)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_alert(
            "https://hooks.example.com/webhook",
            issue.id,
            "New issue",
            "a",
            "NEW",
            self.config.id,
            unmute_reason=None,
        )

        self.config.refresh_from_db()
        self.assertIsNone(self.config.last_failure_timestamp)

        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIn("NEW issue:", sent["text"])
        self.assertEqual(sent["issue"]["project"], "Test project")
        self.assertEqual(sent["issue"]["state"], "NEW")
        self.assertTrue(sent["issue"]["url"].endswith(issue.get_absolute_url()))
        self.assertIsNone(sent["unmute_reason"])

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_alert_message_includes_unmute_reason(self, mock_post):
        issue, _ = get_or_create_issue(project=self.project)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_alert(
            "https://hooks.example.com/webhook",
            issue.id,
            "Unmuted issue",
            "an",
            "UNMUTED",
            self.config.id,
            unmute_reason="volume based unmute",
        )

        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(sent["unmute_reason"], "volume based unmute")

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_test_message_http_error_stores_failure(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = '{"error": "not_found"}'
        http_error = requests.HTTPError()
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        mock_post.return_value = mock_response

        webhook_backend_send_test_message(
            "https://hooks.example.com/webhook",
            "Test project",
            "Test Webhook",
            self.config.id,
        )

        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_failure_timestamp)
        self.assertEqual(self.config.last_failure_status_code, 404)
        self.assertTrue(self.config.last_failure_is_json)
        self.assertEqual(self.config.last_failure_error_type, "HTTPError")

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_test_message_connection_error_stores_failure(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("Connection failed")

        webhook_backend_send_test_message(
            "https://hooks.example.com/webhook",
            "Test project",
            "Test Webhook",
            self.config.id,
        )

        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_failure_timestamp)
        self.assertIsNone(self.config.last_failure_status_code)
        self.assertEqual(self.config.last_failure_error_type, "ConnectionError")

    @patch('alerts.service_backends.base.requests.post')
    def test_test_message_blocked_target_stores_failure_without_network_call(self, mock_post):
        webhook_backend_send_test_message(
            "http://10.0.0.42/hooks/test",
            "Test project",
            "Test Webhook",
            self.config.id,
        )

        mock_post.assert_not_called()
        self.config.refresh_from_db()
        self.assertEqual(self.config.last_failure_error_type, "ValueError")
        self.assertIn("non-global IP address", self.config.last_failure_error_message)

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_alert_custom_template_renders_valid_json(self, mock_post):
        issue, _ = get_or_create_issue(project=self.project)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_alert(
            "https://hooks.example.com/webhook",
            issue.id,
            "New issue",
            "a",
            "NEW",
            self.config.id,
            unmute_reason=None,
            body_template='{"text": $summary, "reason": $alert_reason, "url": $issue_url}',
        )

        # the rendered body is valid JSON, and only carries the template's keys (not the default shape)
        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(set(sent.keys()), {"text", "reason", "url"})
        self.assertIn("NEW issue:", sent["text"])
        self.assertEqual(sent["reason"], "NEW")
        self.assertTrue(sent["url"].endswith(issue.get_absolute_url()))

    @patch('issues.models.Issue.title', return_value='Broke on "quotes" and\nnewlines')
    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_alert_custom_template_quoted_title_stays_valid_json(self, mock_post, mock_title):
        issue, _ = get_or_create_issue(project=self.project)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_alert(
            "https://hooks.example.com/webhook",
            issue.id,
            "New issue",
            "a",
            "NEW",
            self.config.id,
            unmute_reason=None,
            body_template='{"title": $issue_title}',
        )

        # JSON-encoded substitution keeps the body valid despite quotes/newlines in the title
        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(sent["title"], 'Broke on "quotes" and\nnewlines')

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_alert_custom_template_missing_unmute_reason_renders_null(self, mock_post):
        issue, _ = get_or_create_issue(project=self.project)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_alert(
            "https://hooks.example.com/webhook",
            issue.id,
            "New issue",
            "a",
            "NEW",
            self.config.id,
            unmute_reason=None,
            body_template='{"unmute_reason": $unmute_reason}',
        )

        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIsNone(sent["unmute_reason"])

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_test_message_custom_template_renders_valid_json(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_test_message(
            "https://hooks.example.com/webhook",
            "Test project",
            "Test Webhook",
            self.config.id,
            body_template='{"text": $summary, "reason": $alert_reason}',
        )

        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIn("Test message", sent["text"])
        self.assertEqual(sent["reason"], "TEST")

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_alert_empty_body_template_posts_default_payload(self, mock_post):
        # production persists "" for a blank field (not None); "" must fall back to the default payload.
        issue, _ = get_or_create_issue(project=self.project)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_alert(
            "https://hooks.example.com/webhook",
            issue.id,
            "New issue",
            "a",
            "NEW",
            self.config.id,
            unmute_reason=None,
            body_template="",
        )

        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIn("NEW issue:", sent["text"])
        self.assertEqual(sent["issue"]["project"], "Test project")
        self.assertEqual(sent["issue"]["state"], "NEW")

    @patch('alerts.service_backends.base.BaseWebhookBackend.safe_post')
    def test_alert_custom_template_friendly_id(self, mock_post):
        issue, _ = get_or_create_issue(project=self.project)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        webhook_backend_send_alert(
            "https://hooks.example.com/webhook",
            issue.id,
            "New issue",
            "a",
            "NEW",
            self.config.id,
            unmute_reason=None,
            body_template='{"id": $issue_friendly_id}',
        )

        sent = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(sent["id"], issue.friendly_id())
