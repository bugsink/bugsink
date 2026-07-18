from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.checks import run_checks
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.base import OperationCategory
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from .models import AuthToken

User = get_user_model()


class MigrationShapeTestCase(SimpleTestCase):
    # Because of what a migration is we can't go back in time and retroactively fix these so we'll just document them.
    known_bad_mixed_data_schema_migrations = {
        ("issues", "0024_turningpoint_project_alter_not_null"),
        ("phonehome", "0001_b_squashed_initial"),
        ("projects", "0017_project_issue_count"),
    }

    def test_first_party_migrations_do_not_mix_schema_and_data_operations(self):
        # It is my experience that having RunPython and schema changes in separate migration files is very useful: when
        # things go sideways this allows for much more finegrained replaying/rolling back. This test enforces that. If
        # your migration file tripped it just split it in 2 parts.

        migration_loader = MigrationLoader(None, ignore_no_migrations=True)
        bugsink_app_labels = set(settings.BUGSINK_APPS)

        mixed_migrations = {
            key: [operation.__class__.__name__ for operation in migration.operations]
            for key, migration in sorted(migration_loader.graph.nodes.items())
            if key[0] in bugsink_app_labels and self._mixes_data_and_schema_operations(migration.operations)
        }

        unexpected_migrations = set(mixed_migrations) - self.known_bad_mixed_data_schema_migrations
        self.assertEqual(
            set(),
            unexpected_migrations,
            "Migrations must not mix data operations with schema operations: %s" % {
                "%s.%s" % key: mixed_migrations[key] for key in sorted(unexpected_migrations)
            },
        )

    @staticmethod
    def _mixes_data_and_schema_operations(operations):
        has_data_operation = any(
            operation.category in (OperationCategory.PYTHON, OperationCategory.SQL)
            for operation in operations
        )
        has_schema_operation = any(
            operation.category not in (OperationCategory.PYTHON, OperationCategory.SQL)
            for operation in operations
        )

        return has_data_operation and has_schema_operation


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


class AuthTokenDescriptionUpdateTestCase(TransactionTestCase):
    """Editing one token's description must not touch any other token (regression test)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(
            User.objects.create_superuser(username="admin", password="admin", email="admin@example.org"))

    def test_update_description_targets_only_the_clicked_token(self):
        token_1 = AuthToken.objects.create(description="first")
        token_2 = AuthToken.objects.create(description="second")

        # A single <form> wraps all rows, so the browser posts every row's description input.
        response = self.client.post(reverse("auth_token_list"), {
            "action": f"update_description:{token_1.pk}",
            f"description-{token_1.pk}": "updated first",
            f"description-{token_2.pk}": "second",
        })
        self.assertEqual(302, response.status_code)

        token_1.refresh_from_db()
        token_2.refresh_from_db()
        self.assertEqual("updated first", token_1.description)
        self.assertEqual("second", token_2.description)


class AuthTokenListTestCase(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(
            User.objects.create_superuser(username="admin", password="admin", email="admin@example.org"))

    def test_tokens_are_hidden_with_independent_reveal_buttons(self):
        token_1 = AuthToken.objects.create()
        token_2 = AuthToken.objects.create()

        response = self.client.get(reverse("auth_token_list"))

        self.assertContains(response, "•" * 40, count=2)
        self.assertContains(response, f'id="token-hidden-{token_1.pk}"')
        self.assertContains(response, f'id="token-revealed-{token_1.pk}" class="hidden font-mono"')
        self.assertContains(response, f'id="token-toggle-{token_1.pk}"')
        self.assertContains(response, f'id="token-hidden-{token_2.pk}"')
        self.assertContains(response, f'id="token-revealed-{token_2.pk}" class="hidden font-mono"')
        self.assertContains(response, f'id="token-toggle-{token_2.pk}"')
