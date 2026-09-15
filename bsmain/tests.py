from contextlib import redirect_stdout
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.checks import run_checks
from django.core.management import call_command
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.base import OperationCategory
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bugsink.api_capabilities import CAPABILITIES
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project, ProjectVisibility

from .forms import AuthTokenForm
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


class AuthTokenFormTestCase(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="user", password="user", email="user@example.org")
        self.superuser = User.objects.create_superuser(
            username="admin", password="admin", email="admin@example.org")

    def test_normal_user_can_only_choose_projects_from_the_project_list(self):
        visible_project = Project.objects.create(name="Visible", visibility=ProjectVisibility.DISCOVERABLE)
        hidden_project = Project.objects.create(name="Hidden", visibility=ProjectVisibility.TEAM_MEMBERS)

        form = AuthTokenForm(user=self.user)

        self.assertTrue(form.fields["is_user_bound"].disabled)
        self.assertTrue(form.fields["is_user_bound"].initial)
        self.assertEqual("All my projects", form.fields["project"].empty_label)
        self.assertEqual([visible_project], list(form.fields["project"].queryset))

        tampered_form = AuthTokenForm({
            "description": "Hidden project token",
            "project": hidden_project.pk,
            "issues_read": True,
        }, user=self.user)
        self.assertFalse(tampered_form.is_valid())
        self.assertIn("Select a valid choice", tampered_form.errors["project"][0])

    def test_token_requires_a_capability(self):
        form = AuthTokenForm({"description": "Powerless token"}, user=self.superuser)

        self.assertFalse(form.is_valid())
        self.assertEqual(["Select at least one capability."], form.non_field_errors())

    def test_project_token_cannot_manage_projects_or_teams(self):
        project = Project.objects.create(name="One project")
        form = AuthTokenForm({
            "description": "Bad project token",
            "project": project.pk,
            "projects_read": True,
        }, user=self.superuser)

        self.assertFalse(form.is_valid())
        self.assertIn("Project-bound tokens cannot have capabilities: projects:read.", form.errors["project"])

    def test_personal_tokens_are_tied_to_the_requesting_user(self):
        normal_user_form = AuthTokenForm({
            "description": "My token",
            "issues_read": True,
        }, user=self.user)
        superuser_form = AuthTokenForm({
            "description": "My admin token",
            "is_user_bound": True,
            "issues_read": True,
        }, user=self.superuser)

        self.assertTrue(normal_user_form.is_valid(), normal_user_form.errors)
        self.assertTrue(superuser_form.is_valid(), superuser_form.errors)
        normal_user_token = normal_user_form.save()
        superuser_token = superuser_form.save()
        self.assertEqual(self.user, normal_user_token.user)
        self.assertTrue(normal_user_token.is_user_bound)
        self.assertEqual(self.superuser, superuser_token.user)
        self.assertTrue(superuser_token.is_user_bound)


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

    def test_superuser_can_create_an_installation_service_token(self):
        response = self.client.post(reverse("auth_token_create"), {
            "description": "Deployment token",
            "issues_read": True,
        })

        self.assertEqual(302, response.status_code)
        token = AuthToken.objects.get()
        self.assertFalse(token.is_user_bound)
        self.assertFalse(token.is_project_bound)
        self.assertEqual({"issues:read"}, token.capabilities)

    def test_normal_user_lists_and_revokes_only_their_own_tokens(self):
        user = User.objects.create_user(username="other-user", password="user")
        another_user = User.objects.create_user(username="another-user", password="user")
        own_token = AuthToken.objects.create(
            description="Own token", is_user_bound=True, user=user, issues_read=True)
        other_token = AuthToken.objects.create(
            description="Other token", is_user_bound=True, user=another_user, issues_read=True)
        service_token = AuthToken.objects.create(description="Service token", issues_read=True)
        self.client.force_login(user)

        response = self.client.get(reverse("auth_token_list"))

        self.assertContains(response, "Own token")
        self.assertNotContains(response, "Other token")
        self.assertNotContains(response, "Service token")

        response = self.client.post(reverse("auth_token_list"), {"action": f"revoke:{other_token.pk}"})

        self.assertEqual(404, response.status_code)
        response = self.client.post(reverse("auth_token_list"), {"action": f"revoke:{own_token.pk}"})
        self.assertEqual(302, response.status_code)
        own_token.refresh_from_db()
        other_token.refresh_from_db()
        service_token.refresh_from_db()
        self.assertLessEqual(own_token.expires_at, timezone.now())
        self.assertIsNone(other_token.expires_at)
        self.assertIsNone(service_token.expires_at)

    def test_revoke_expires_the_token_now_and_hides_it_from_the_list(self):
        token = AuthToken.objects.create(
            description="Deploy token",
            expires_at=timezone.now() + timedelta(days=30),
        )

        response = self.client.get(reverse("auth_token_list"))
        self.assertContains(response, "Deploy token")

        response = self.client.post(reverse("auth_token_list"), {"action": f"revoke:{token.pk}"})

        self.assertEqual(302, response.status_code)
        token.refresh_from_db()
        self.assertLessEqual(token.expires_at, timezone.now())
        response = self.client.get(reverse("auth_token_list"))
        self.assertNotContains(response, "Deploy token")
        self.assertNotContains(response, f'id="token-hidden-{token.pk}"')


class CreateAuthTokenCommandTests(TransactionTestCase):
    def test_command_creates_a_full_access_installation_service_token(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            call_command("create_auth_token")

        token = AuthToken.objects.get()
        self.assertEqual(token.token, stdout.getvalue().strip())
        self.assertFalse(token.is_user_bound)
        self.assertFalse(token.is_project_bound)
        self.assertEqual(set(CAPABILITIES), token.capabilities)
