from io import StringIO
from unittest import skipIf, skipUnless

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from bugsink.app_settings import get_settings, override_settings, CB_ANYBODY
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from .checks import check_emails_are_lowercase
from .models import EmailVerification
from .utils import normalize_email


User = get_user_model()


class ResetPasswordRedirectTestCase(TransactionTestCase):
    def _verification_for(self, email="user@example.com"):
        user = User.objects.create_user(username=email, email=email, is_active=False)
        return EmailVerification.objects.create(user=user, email=email)

    def test_reset_password_rejects_external_next_redirect(self):
        verification = self._verification_for()

        response = self.client.post(
            reverse("reset_password", kwargs={"token": verification.token}),
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

        response = self.client.post(
            reverse("reset_password", kwargs={"token": verification.token}),
            {
                "new_password1": "S3curePassw0rd!",
                "new_password2": "S3curePassw0rd!",
                "next": "/accounts/preferences/",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/accounts/preferences/")


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


class NormalizeEmailTestCase(TestCase):
    def test_off_by_default(self):
        self.assertEqual("User.Name@Example.COM", normalize_email("User.Name@Example.COM"))

    def test_on(self):
        with override_settings(USER_EMAIL_CASE_INSENSITIVE=True):
            self.assertEqual("user.name@example.com", normalize_email("User.Name@Example.COM"))
            self.assertEqual("already@lower.com", normalize_email("already@lower.com"))
            self.assertEqual("", normalize_email(""))
            self.assertIsNone(normalize_email(None))


class CaseInsensitiveEmailTestCase(TransactionTestCase):
    def test_signup_and_login_ignore_case(self):
        with override_settings(
                USER_EMAIL_CASE_INSENSITIVE=True, USER_REGISTRATION=CB_ANYBODY,
                USER_REGISTRATION_VERIFY_EMAIL=False):
            response = self.client.post(reverse("signup"), {
                "username": "User.Name@Example.COM",
                "password1": "S3curePassw0rd!",
                "password2": "S3curePassw0rd!",
            })
            self.assertEqual(response.status_code, 302)

            user = User.objects.get()
            self.assertEqual("user.name@example.com", user.username)
            self.assertEqual("user.name@example.com", user.email)

            self.client.logout()
            response = self.client.post(reverse("login"), {
                "username": "USER.NAME@example.com",
                "password": "S3curePassw0rd!",
            })
            self.assertEqual(response.status_code, 302)

    def test_request_reset_password_ignores_case(self):
        User.objects.create_user(username="user@example.com", email="user@example.com")

        with override_settings(USER_EMAIL_CASE_INSENSITIVE=True):
            response = self.client.post(reverse("request_reset_password"), {"email": "User@Example.com"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(1, EmailVerification.objects.count())


class LowercaseUserEmailsCommandTestCase(TransactionTestCase):
    def test_lowercases_and_reports(self):
        User.objects.create_user(username="Mixed@Example.com", email="Mixed@Example.com")
        User.objects.create_user(username="lower@example.com", email="lower@example.com")

        stdout = StringIO()
        call_command("lowercase_user_emails", stdout=stdout)

        self.assertTrue(User.objects.filter(username="mixed@example.com", email="mixed@example.com").exists())
        self.assertIn("1 user(s) updated", stdout.getvalue())

    @skipIf(connection.vendor == "mysql", "MySQL's collation is case-insensitive, so such users cannot coexist")
    def test_refuses_on_collision(self):
        User.objects.create_user(username="Dup@Example.com", email="Dup@Example.com")
        User.objects.create_user(username="dup@example.com", email="dup@example.com")

        with self.assertRaises(CommandError):
            call_command("lowercase_user_emails", stdout=StringIO())


class MixedCaseCheckTestCase(TransactionTestCase):
    def test_no_error_when_setting_is_off(self):
        User.objects.create_user(username="Mixed@Example.com", email="Mixed@Example.com")
        self.assertEqual([], check_emails_are_lowercase(None))

    @skipIf(connection.vendor == "mysql", "MySQL matches case-insensitively; nobody is locked out")
    def test_error_when_setting_is_on_and_mixed_case_users_exist(self):
        User.objects.create_user(username="Mixed@Example.com", email="Mixed@Example.com")

        with override_settings(USER_EMAIL_CASE_INSENSITIVE=True):
            errors = check_emails_are_lowercase(None)

        self.assertEqual(1, len(errors))
        self.assertEqual("users.E001", errors[0].id)
        self.assertIn("Mixed@Example.com", errors[0].msg)

    @skipUnless(connection.vendor == "mysql", "only MySQL matches case-insensitively by collation")
    def test_no_error_on_mysql_despite_mixed_case_users(self):
        User.objects.create_user(username="Mixed@Example.com", email="Mixed@Example.com")

        with override_settings(USER_EMAIL_CASE_INSENSITIVE=True):
            self.assertEqual([], check_emails_are_lowercase(None))

    def test_no_error_once_lowercased(self):
        User.objects.create_user(username="Mixed@Example.com", email="Mixed@Example.com")
        call_command("lowercase_user_emails", stdout=StringIO())

        with override_settings(USER_EMAIL_CASE_INSENSITIVE=True):
            self.assertEqual([], check_emails_are_lowercase(None))
