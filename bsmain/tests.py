from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings


class SystemChecksTestCase(SimpleTestCase):
    def _warnings(self):
        return [warning for warning in run_checks(tags=["bsmain"]) if warning.id == "bsmain.W006"]

    @override_settings(DEFAULT_FROM_EMAIL="Bugsink <bugsink@example.org>", SERVER_EMAIL="server@example.org")
    def test_email_sender_domain_check_allows_non_bugsink_domain(self):
        self.assertEqual([], self._warnings())

    @override_settings(DEFAULT_FROM_EMAIL="Bugsink <alerts@bugsink.com>", SERVER_EMAIL="server@example.org")
    def test_email_sender_domain_check_warns_for_default_from_email(self):
        warnings = self._warnings()

        self.assertEqual(1, len(warnings))
        self.assertEqual(
            "DEFAULT_FROM_EMAIL uses the bugsink.com domain, but ALLOWED_HOSTS does not. This looks like a "
            "self-hosted Bugsink sending email as bugsink.com. That is effectively spam, deliverability will "
            "suffer badly, and those messages show up in Bugsink's DKIM reports. Configure your own sender "
            "address instead.",
            warnings[0].msg,
        )

    @override_settings(DEFAULT_FROM_EMAIL="Bugsink <bugsink@example.org>", SERVER_EMAIL="server@bugsink.com")
    def test_email_sender_domain_check_warns_for_server_email(self):
        warnings = self._warnings()

        self.assertEqual(1, len(warnings))
        self.assertEqual(
            "SERVER_EMAIL uses the bugsink.com domain, but ALLOWED_HOSTS does not. This looks like a "
            "self-hosted Bugsink sending email as bugsink.com. That is effectively spam, deliverability will "
            "suffer badly, and those messages show up in Bugsink's DKIM reports. Configure your own sender "
            "address instead.",
            warnings[0].msg,
        )

    @override_settings(
        DEFAULT_FROM_EMAIL="alerts@bugsink.com",
        SERVER_EMAIL="server@example.org",
        ALLOWED_HOSTS=["selfhosted.bugsink.com"],
    )
    def test_email_sender_domain_check_allows_bugsink_domain_when_allowed_hosts_match(self):
        self.assertEqual([], self._warnings())
