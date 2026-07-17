import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from bugsink.context_processors import get_email_failure_warnings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from .models import Installation
from .tasks import _make_message_body


class PhoneHomeTests(TestCase):

    def test_make_message_body(self):
        # simple "does not crash" test (at least tests the various database getter code paths don't crash)
        _make_message_body()


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
