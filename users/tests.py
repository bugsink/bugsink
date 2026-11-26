from datetime import timedelta
from io import StringIO
from importlib import import_module
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from bugsink.app_settings import get_settings, override_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from bsmain.models import AuthToken
from projects.models import Project, ProjectMembership, ProjectRole
from teams.models import Team, TeamMembership, TeamRole

from .models import EmailVerification


User = get_user_model()


class UserDeactivationTestCase(TransactionTestCase):
    def test_deactivation_revokes_memberships_tokens_privileges_and_sessions(self):
        admin = User.objects.create_superuser(username="admin@example.com", password="test")
        user = User.objects.create_superuser(username="former-admin@example.com", password="old-password")
        team = Team.objects.create(name="Old team")
        project = Project.objects.create(name="Old project", team=team)
        TeamMembership.objects.create(team=team, user=user, role=TeamRole.ADMIN, accepted=True)
        ProjectMembership.objects.create(project=project, user=user, role=ProjectRole.ADMIN, accepted=False)
        verification = EmailVerification.objects.create(user=user, email=user.username)
        token = AuthToken.objects.create(user=user, is_user_bound=True, projects_read=True)
        service_token = AuthToken.objects.create(project=project, is_project_bound=True, projects_read=True)
        old_session = Client()
        old_session.force_login(user)
        self.client.force_login(admin)

        response = self.client.post(reverse("user_list"), {"action": f"deactivate:{user.pk}"})

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_deactivated)
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_usable_password())
        self.assertFalse(TeamMembership.objects.filter(user=user).exists())
        self.assertFalse(ProjectMembership.objects.filter(user=user).exists())
        self.assertFalse(EmailVerification.objects.filter(pk=verification.pk).exists())
        self.assertFalse(AuthToken.objects.filter(pk=token.pk).exists())
        self.assertTrue(AuthToken.objects.filter(pk=service_token.pk).exists())

        self.client.post(reverse("user_list"), {"action": f"activate:{user.pk}"})
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_deactivated)
        self.assertEqual(old_session.get(reverse("preferences")).status_code, 302)
        self.assertFalse(old_session.login(username=user.username, password="old-password"))
        self.assertFalse(TeamMembership.objects.filter(user=user).exists())
        self.assertFalse(AuthToken.objects.filter(pk=token.pk).exists())

    def test_deactivated_user_cannot_request_or_redeem_email_recovery(self):
        user = User.objects.create_user(
            username="deactivated@example.com", email="deactivated@example.com",
            is_active=False, is_deactivated=True, password="old-password")
        verification = EmailVerification.objects.create(user=user, email=user.username)

        for view in ["request_reset_password", "resend_confirmation"]:
            response = self.client.post(reverse(view), {"email": user.username})
            self.assertEqual(response.status_code, 404)

        for view in ["confirm_email", "reset_password"]:
            response = self.client.post(reverse(view, kwargs={"token": verification.token}), {
                "new_password1": "NewSecurePassw0rd!", "new_password2": "NewSecurePassw0rd!",
            })
            self.assertEqual(response.status_code, 404)

        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password("old-password"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(EmailVerification.objects.filter(user=user).count(), 1)

    @patch("users.views.send_reset_email.delay")
    def test_active_user_can_request_and_complete_password_reset(self, send_reset):
        user = User.objects.create_user(username="active@example.com", password="old-password")

        response = self.client.post(reverse("request_reset_password"), {"email": user.username})

        self.assertEqual(response.status_code, 200)
        verification = EmailVerification.objects.get(user=user)
        send_reset.assert_called_once_with(user.username, verification.token)
        response = self.client.get(reverse("reset_password", kwargs={"token": verification.token}))
        response = self.client.post(response["Location"], {
            "new_password1": "NewSecurePassw0rd!", "new_password2": "NewSecurePassw0rd!",
        })
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("NewSecurePassw0rd!"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    @patch("users.views.send_confirm_email.delay")
    def test_unconfirmed_signup_can_resend_confirmation_but_not_request_password_reset(self, send_confirmation):
        user = User.objects.create_user(username="pending@example.com", is_active=False, password="signup-password")

        response = self.client.post(reverse("request_reset_password"), {"email": user.username})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(EmailVerification.objects.filter(user=user).exists())

        response = self.client.post(reverse("resend_confirmation"), {"email": user.username})
        self.assertEqual(response.status_code, 200)
        verification = EmailVerification.objects.get(user=user)
        send_confirmation.assert_called_once_with(user.username, verification.token)

        response = self.client.post(reverse("confirm_email", kwargs={"token": verification.token}))
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("signup-password"))


class ExistingInactiveUsersMigrationTestCase(TransactionTestCase):
    def test_only_recent_unconfirmed_accounts_are_preserved(self):
        now = timezone.now()
        team = Team.objects.create(name="Existing team")
        project = Project.objects.create(name="Existing project", team=team)
        cases = [
            # name, account age, token age, previously logged in, privileged, remains pending
            ("pending", 30, 30, False, False, True),
            ("old-account", 61, 10, False, False, False),
            ("expired-token", 30, 61, False, False, False),
            ("no-token", 30, None, False, False, False),
            ("previous-login", 30, 10, True, False, False),
            ("privileged", 30, 10, False, True, False),
        ]
        for name, account_age, token_age, logged_in, privileged, pending in cases:
            user = User.objects.create_user(
                username=name, is_active=False, password="signup-password",
                date_joined=now - timedelta(seconds=account_age),
                last_login=now if logged_in else None, is_superuser=privileged, is_staff=privileged)
            TeamMembership.objects.create(team=team, user=user)
            ProjectMembership.objects.create(project=project, user=user)
            AuthToken.objects.create(user=user, is_user_bound=True)
            if token_age is not None:
                verification = EmailVerification.objects.create(user=user, email="user@example.com")
                EmailVerification.objects.filter(pk=verification.pk).update(
                    created_at=now - timedelta(seconds=token_age))

        active_user = User.objects.create_superuser(username="active", password="test")
        migration = import_module("users.migrations.0006_deactivate_existing_users")
        historical_apps = MigrationLoader(connection).project_state().apps
        get_settings()
        with override_settings(USER_REGISTRATION_VERIFY_EMAIL_EXPIRY=60), connection.schema_editor() as schema_editor:
            migration.deactivate_existing_users(historical_apps, schema_editor)

        for name, _, _, _, _, pending in cases:
            user = User.objects.get(username=name)
            self.assertEqual(user.is_deactivated, not pending, name)
            self.assertFalse(user.is_active, name)
            self.assertEqual(user.has_usable_password(), pending, name)
            self.assertFalse(user.is_superuser, name)
            self.assertFalse(user.is_staff, name)
            self.assertEqual(TeamMembership.objects.filter(user=user).exists(), pending, name)
            self.assertEqual(ProjectMembership.objects.filter(user=user).exists(), pending, name)
            self.assertEqual(AuthToken.objects.filter(user=user).exists(), pending, name)
            self.assertEqual(EmailVerification.objects.filter(user=user).exists(), pending, name)

        active_user.refresh_from_db()
        self.assertTrue(active_user.is_active)
        self.assertTrue(active_user.is_superuser)
        self.assertTrue(active_user.check_password("test"))


class EmailVerificationExpiryTestCase(TransactionTestCase):
    def _verification_for(self, email, age_seconds):
        user = User.objects.create_user(username=email, email=email, is_active=False)
        verification = EmailVerification.objects.create(user=user, email=email)
        EmailVerification.objects.filter(pk=verification.pk).update(
            created_at=timezone.now() - timedelta(seconds=age_seconds))
        return user, verification

    def test_recent_token_can_confirm_email(self):
        user, verification = self._verification_for("recent@example.com", 59)

        get_settings()
        with override_settings(USER_REGISTRATION_VERIFY_EMAIL_EXPIRY=60):
            response = self.client.post(reverse("confirm_email", kwargs={"token": verification.token}))

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertFalse(EmailVerification.objects.filter(pk=verification.pk).exists())

    def test_expired_token_cannot_confirm_email(self):
        user, verification = self._verification_for("expired-confirm@example.com", 61)

        get_settings()
        with override_settings(USER_REGISTRATION_VERIFY_EMAIL_EXPIRY=60):
            response = self.client.get(reverse("confirm_email", kwargs={"token": verification.token}))

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("_auth_user_id", self.client.session)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_expired_token_cannot_reset_password(self):
        user, verification = self._verification_for("expired-reset@example.com", 61)

        get_settings()
        with override_settings(USER_REGISTRATION_VERIFY_EMAIL_EXPIRY=60):
            response = self.client.get(reverse("reset_password", kwargs={"token": verification.token}))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(user.has_usable_password())


class ResetPasswordRedirectTestCase(TransactionTestCase):
    def _verification_for(self, email="user@example.com"):
        user = User.objects.create_user(username=email, email=email, is_active=False)
        return EmailVerification.objects.create(user=user, email=email)

    def test_reset_password_rejects_external_next_redirect(self):
        verification = self._verification_for()
        self.client.get(reverse("reset_password", kwargs={"token": verification.token}))

        response = self.client.post(
            reverse("reset_password", kwargs={"token": "set-password"}),
            {
                "new_password1": "S3curePassw0rd!",
                "new_password2": "S3curePassw0rd!",
                "next": "https://evil.example/phish",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("home"))

    def test_reset_password_allows_local_next_redirect(self):
        verification = self._verification_for("local@example.com")
        self.client.get(reverse("reset_password", kwargs={"token": verification.token}))

        response = self.client.post(
            reverse("reset_password", kwargs={"token": "set-password"}),
            {
                "new_password1": "S3curePassw0rd!",
                "new_password2": "S3curePassw0rd!",
                "next": "/accounts/preferences/",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/accounts/preferences/")

    def test_reset_form_uses_session_token_and_cannot_be_cached(self):
        verification = self._verification_for()
        reset_url = reverse("reset_password", kwargs={"token": "set-password"})
        other_browser = Client()
        self.assertEqual(other_browser.get(reset_url).status_code, 404)

        response = self.client.get(reverse("reset_password", kwargs={"token": verification.token}), {
            "next": reverse("preferences"),
        })

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(verification.token, response["Location"])
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.get(response["Location"])
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, verification.token)
        self.assertEqual(response.context["next"], reverse("preferences"))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(other_browser.get(reset_url).status_code, 404)

        response = self.client.post(reset_url, {"new_password1": "one", "new_password2": "different"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(EmailVerification.objects.filter(pk=verification.pk).exists())

        response = self.client.post(reset_url, {
            "new_password1": "NewSecurePassw0rd!", "new_password2": "NewSecurePassw0rd!",
            "next": reverse("preferences"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("preferences"))
        self.assertNotIn("_password_reset_token", self.client.session)
        self.assertEqual(self.client.get(reset_url).status_code, 404)


class CreateSetPasswordLinkCommandTestCase(TransactionTestCase):
    def test_create_set_password_link_prints_reset_password_url(self):
        user = User.objects.create_user(username="command@example.com", email="command@example.com")

        stdout = StringIO()
        call_command("create_set_password_link", "command@example.com", stdout=stdout)

        verification = EmailVerification.objects.get(user=user)
        self.assertEqual(
            stdout.getvalue().strip(),
            get_settings().BASE_URL + reverse("reset_password", kwargs={"token": verification.token}),
        )


class PreferencesPasswordTestCase(TransactionTestCase):
    def test_change_password_page_can_change_own_password(self):
        user = User.objects.create_user(
            username="preferences@example.com",
            email="preferences@example.com",
            password="OldSecurePassw0rd!",
        )
        verification = EmailVerification.objects.create(user=user, email=user.email)
        self.client.force_login(user)

        preferences_response = self.client.get(reverse("preferences"))
        self.assertContains(preferences_response, reverse("change_password"))

        response = self.client.post(reverse("change_password"), {
            "old_password": "OldSecurePassw0rd!",
            "new_password1": "NewSecurePassw0rd!",
            "new_password2": "NewSecurePassw0rd!",
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("preferences"))

        user.refresh_from_db()
        self.assertTrue(user.check_password("NewSecurePassw0rd!"))
        self.assertEqual(self.client.get(reverse("preferences")).status_code, 200)
        self.client.logout()
        response = self.client.get(reverse("reset_password", kwargs={"token": verification.token}))
        self.assertEqual(response.status_code, 404)


class PasswordResetTokensTestCase(TransactionTestCase):
    def test_reset_invalidates_other_outstanding_email_links(self):
        user = User.objects.create_user(
            username="reset@example.com", email="reset@example.com", password="OldSecurePassw0rd!")
        verification = EmailVerification.objects.create(user=user, email=user.email)
        other_verification = EmailVerification.objects.create(user=user, email=user.email)
        other_user = User.objects.create_user(username="other@example.com")
        unrelated_verification = EmailVerification.objects.create(user=other_user, email=other_user.email)

        response = self.client.get(reverse("reset_password", kwargs={"token": verification.token}))
        response = self.client.post(response["Location"], {
            "new_password1": "NewSecurePassw0rd!", "new_password2": "NewSecurePassw0rd!",
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(EmailVerification.objects.filter(user=user).exists())
        self.assertTrue(EmailVerification.objects.filter(pk=unrelated_verification.pk).exists())
        self.client.logout()
        response = self.client.post(reverse("reset_password", kwargs={"token": other_verification.token}), {
            "new_password1": "AnotherSecurePassw0rd!", "new_password2": "AnotherSecurePassw0rd!",
        })
        self.assertEqual(response.status_code, 404)
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewSecurePassw0rd!"))


class EmailChangeTokensTestCase(TransactionTestCase):
    def test_changing_email_invalidates_old_links_but_allows_new_recovery(self):
        user = User.objects.create_user(
            username="before@example.com", email="before@example.com", password="OldSecurePassw0rd!")
        verification = EmailVerification.objects.create(user=user, email=user.email)
        admin = User.objects.create_superuser(username="admin@example.com", password="test")
        self.client.force_login(admin)

        response = self.client.post(reverse("user_edit", kwargs={"user_pk": user.pk}), {
            "username": "after@example.com",
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(EmailVerification.objects.filter(user=user).exists())
        self.client.logout()
        response = self.client.post(reverse("reset_password", kwargs={"token": verification.token}), {
            "new_password1": "AttackerSecurePassw0rd!", "new_password2": "AttackerSecurePassw0rd!",
        })
        self.assertEqual(response.status_code, 404)

        with patch("users.views.send_reset_email.delay") as send_reset:
            response = self.client.post(reverse("request_reset_password"), {"email": "after@example.com"})
        self.assertEqual(response.status_code, 200)
        verification = EmailVerification.objects.get(user=user)
        send_reset.assert_called_once_with("after@example.com", verification.token)
        response = self.client.get(reverse("reset_password", kwargs={"token": verification.token}))
        response = self.client.post(response["Location"], {
            "new_password1": "NewSecurePassw0rd!", "new_password2": "NewSecurePassw0rd!",
        })
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewSecurePassw0rd!"))

    def test_links_for_a_different_email_cannot_confirm_or_reset(self):
        user = User.objects.create_user(username="current@example.com", email="current@example.com", is_active=False)
        verification = EmailVerification.objects.create(user=user, email="previous@example.com")

        for view in ["confirm_email", "reset_password"]:
            response = self.client.post(reverse(view, kwargs={"token": verification.token}), {
                "new_password1": "NewSecurePassw0rd!", "new_password2": "NewSecurePassw0rd!",
            })
            self.assertEqual(response.status_code, 404)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
