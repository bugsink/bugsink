from django.contrib.auth import get_user_model
from django.urls import reverse

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
