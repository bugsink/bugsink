import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse
from bugsink.app_settings import override_settings as override_bugsink_settings
from bugsink.context_processors import get_email_failure_warnings, get_email_quota_warnings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from .models import Installation, OutboundMessage, RemoteMessage, RemoteMessagePart
from .tasks import _make_message_body, _validate_remote_messages, send_if_due


User = get_user_model()


class PhoneHomeTests(TestCase):

    def test_make_message_body(self):
        # simple "does not crash" test (at least tests the various database getter code paths don't crash)
        _make_message_body()

    def test_validate_remote_messages(self):
        expires_at = (timezone.now() + timedelta(days=1)).isoformat()

        self.assertEqual(_validate_remote_messages({
            "messages": [{
                "id": "security-2026-001",
                "applies_until_version": "9999.0.0",
                "parts": [
                    {"text": "Upgrade Bugsink. "},
                    {"text": "Read the advisory", "url": "https://www.bugsink.com/security/2026-001/"},
                ],
                "expires_at": expires_at,
            }],
        }), [{
            "id": "security-2026-001",
            "applies_until_version": "9999.0.0",
            "parts": [
                {"text": "Upgrade Bugsink. "},
                {"text": "Read the advisory", "url": "https://www.bugsink.com/security/2026-001/"},
            ],
            "expires_at": expires_at,
        }])

    def test_validate_remote_messages_rejects_non_https_links(self):
        with self.assertRaisesMessage(ValueError, "Invalid phonehome message URL"):
            _validate_remote_messages({
                "messages": [{
                    "id": "security-2026-001",
                    "applies_until_version": "9999.0.0",
                    "parts": [{"text": "Not an innocent link", "url": "javascript:alert(1)"}],
                    "expires_at": (timezone.now() + timedelta(days=1)).isoformat(),
                }],
            })


class RemoteMessagesTestCase(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.remote_message = RemoteMessage.objects.create(
            key="security-2026-001",
            applies_until_version="9999.0.0",
            expires_at=timezone.now() + timedelta(days=1),
        )
        RemoteMessagePart.objects.create(
            message=self.remote_message,
            position=0,
            text="<strong>Upgrade Bugsink</strong>. ",
        )
        RemoteMessagePart.objects.create(
            message=self.remote_message,
            position=1,
            text="Read the advisory",
            url="https://www.bugsink.com/security/2026-001/",
        )

    @override_bugsink_settings(PHONEHOME=True)
    @patch("phonehome.tasks.requests.post")
    def test_successful_phonehome_updates_remote_messages(self, post):
        remote_messages = [{
            "id": "security-2026-001",
            "applies_until_version": "9999.0.0",
            "parts": [{"text": "Upgrade again."}],
            "expires_at": (timezone.now() + timedelta(days=2)).isoformat(),
        }]
        post.return_value.json.return_value = {"messages": remote_messages}
        self.remote_message.silenced = True
        self.remote_message.save(update_fields=["silenced"])
        old_message = RemoteMessage.objects.create(
            key="old-message",
            applies_until_version="9999.0.0",
            expires_at=timezone.now() + timedelta(days=1),
        )

        send_if_due()

        self.remote_message.refresh_from_db()
        old_message.refresh_from_db()
        self.assertEqual(self.remote_message.applies_until_version, "9999.0.0")
        self.assertEqual(self.remote_message.parts.get().text, "Upgrade again.")
        self.assertTrue(self.remote_message.active)
        self.assertTrue(self.remote_message.silenced)
        self.assertFalse(old_message.active)
        self.assertIsNotNone(OutboundMessage.objects.get().sent_at)

    @override_bugsink_settings(PHONEHOME=True)
    @patch("phonehome.tasks.requests.post")
    def test_invalid_remote_messages_leave_previous_messages_in_place(self, post):
        post.return_value.json.return_value = {
            "messages": [{
                "id": "security-2026-002",
                "applies_until_version": "9999.0.0",
                "parts": [{"text": "Not an innocent link", "url": "javascript:alert(1)"}],
                "expires_at": (timezone.now() + timedelta(days=2)).isoformat(),
            }],
        }

        send_if_due()

        self.remote_message.refresh_from_db()
        self.assertTrue(self.remote_message.active)
        self.assertEqual(self.remote_message.parts.first().text, "<strong>Upgrade Bugsink</strong>. ")
        self.assertIsNotNone(OutboundMessage.objects.get().sent_at)

    def test_remote_message_is_escaped_and_only_shown_to_superusers(self):
        user = User.objects.create_user(username="user", password="user")
        self.client.force_login(user)
        response = self.client.get("/", follow=True)
        self.assertNotContains(response, "Upgrade Bugsink")

        superuser = User.objects.create_superuser(username="admin", password="admin")
        self.client.force_login(superuser)
        response = self.client.get("/", follow=True)
        self.assertContains(response, "&lt;strong&gt;Upgrade Bugsink&lt;/strong&gt;", html=False)
        self.assertNotContains(response, "<strong>Upgrade Bugsink</strong>", html=False)
        self.assertContains(response, 'href="https://www.bugsink.com/security/2026-001/"')

    def test_superuser_can_silence_a_remote_message(self):
        superuser = User.objects.create_superuser(username="admin", password="admin")
        self.client.force_login(superuser)

        response = self.client.post(
            reverse("silence_remote_message", kwargs={"message_id": "security-2026-001"}),
            {"next": "/"},
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.remote_message.refresh_from_db()
        self.assertTrue(self.remote_message.silenced)

    def test_expired_remote_message_is_not_shown(self):
        self.remote_message.expires_at = timezone.now() - timedelta(seconds=1)
        self.remote_message.save(update_fields=["expires_at"])

        superuser = User.objects.create_superuser(username="admin", password="admin")
        self.client.force_login(superuser)
        response = self.client.get("/", follow=True)

        self.assertNotContains(response, "Upgrade Bugsink")

    def test_remote_message_is_not_shown_after_its_last_applicable_version(self):
        self.remote_message.applies_until_version = "0.0.1"
        self.remote_message.save(update_fields=["applies_until_version"])

        superuser = User.objects.create_superuser(username="admin", password="admin")
        self.client.force_login(superuser)
        response = self.client.get("/", follow=True)

        self.assertNotContains(response, "Upgrade Bugsink")


class EmailSendingDiagnosticsTestCase(TransactionTestCase):

    def test_record_email_attempt_caps_at_ten(self):
        base = timezone.now()

        for i in range(12):
            Installation.record_email_attempt(
                i % 2 == 0,
                i / 10,
                "SMTPConnectError" if i % 2 else None,
                base + timedelta(seconds=i),
            )

        diagnostics = json.loads(Installation.objects.get().email_sending_diagnostics)

        self.assertEqual(10, len(diagnostics["attempts"]))
        self.assertEqual((base + timedelta(seconds=2)).isoformat(), diagnostics["attempts"][0]["at"])
        self.assertEqual((base + timedelta(seconds=11)).isoformat(), diagnostics["attempts"][-1]["at"])
        self.assertEqual("SMTPConnectError", diagnostics["attempts"][-1]["error"])

    def test_email_failure_warning_uses_recent_failure_rate(self):
        installation = Installation.objects.get()
        now = timezone.now()
        attempts = [
            {"at": (now - timedelta(minutes=4, seconds=i)).isoformat(), "ok": i < 2, "duration": 0.1}
            for i in range(5)
        ]
        installation.email_sending_diagnostics = json.dumps({"attempts": attempts})

        warnings = get_email_failure_warnings(installation, now)

        self.assertEqual(1, len(warnings))
        self.assertEqual(
            "Email sending appears to be failing: 3 of 5 recent email attempts failed.",
            warnings[0].message,
        )

    def test_email_failure_warning_ignores_old_attempts(self):
        installation = Installation.objects.get()
        now = timezone.now()
        attempts = [
            {"at": (now - timedelta(minutes=6, seconds=i)).isoformat(), "ok": False, "duration": 0.1}
            for i in range(10)
        ]
        installation.email_sending_diagnostics = json.dumps({"attempts": attempts})

        self.assertEqual([], get_email_failure_warnings(installation, now))


class EmailQuotaTestCase(TransactionTestCase):

    def test_hourly_email_quota(self):
        now = timezone.now()

        with override_bugsink_settings(MAX_EMAILS_PER_HOUR=2, MAX_EMAILS_PER_MONTH=None):
            self.assertTrue(Installation.check_and_inc_email_quota(now))
            self.assertTrue(Installation.check_and_inc_email_quota(now))
            self.assertFalse(Installation.check_and_inc_email_quota(now))

        usage = json.loads(Installation.objects.get().email_quota_usage)
        self.assertEqual(2, usage["per_hour"][now.strftime("%Y-%m-%dT%H")])
        self.assertEqual(2, usage["per_month"][now.strftime("%Y-%m")])

    def test_hourly_email_quota_warning(self):
        now = timezone.now()
        installation = Installation.objects.get()
        installation.email_quota_usage = json.dumps({
            "per_hour": {now.strftime("%Y-%m-%dT%H"): 2},
            "per_month": {},
        })

        with override_bugsink_settings(MAX_EMAILS_PER_HOUR=2, MAX_EMAILS_PER_MONTH=None):
            warnings = get_email_quota_warnings(installation, now)

        self.assertEqual(1, len(warnings))
        self.assertEqual(
            "Bugsink has sent 2 emails this hour, which is the maximum. "
            "No more emails will be sent until the next hour.",
            warnings[0].message,
        )
