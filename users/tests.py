from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from bugsink.app_settings import get_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from .models import EmailVerification


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
    def test_preferences_can_change_own_password(self):
        user = User.objects.create_user(
            username="preferences@example.com",
            email="preferences@example.com",
            password="OldSecurePassw0rd!",
        )
        self.client.force_login(user)

        response = self.client.post(reverse("preferences"), {
            "action": "set_password",
            "old_password": "OldSecurePassw0rd!",
            "new_password1": "NewSecurePassw0rd!",
            "new_password2": "NewSecurePassw0rd!",
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("preferences"))

        user.refresh_from_db()
        self.assertTrue(user.check_password("NewSecurePassw0rd!"))
        self.assertEqual(self.client.get(reverse("preferences")).status_code, 200)
