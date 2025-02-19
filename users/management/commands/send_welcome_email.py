from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from users.models import EmailVerification
from users.tasks import send_welcome_email

UserModel = get_user_model()


class Command(BaseCommand):
    help = "Send a welcome email to a user; allowing them to set their password."

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, required=True)
        parser.add_argument(
            "--reason", type=str, required=True,
            help="The reason the user was added; will be the first line of the email body.")

    def handle(self, *args, **options):
        email = options["email"]
        user = UserModel.objects.get(email=email)

        # copy/paste from views.py (excluding the comments)
        verification = EmailVerification.objects.create(user=user, email=user.username)
        send_welcome_email.delay(user.email, verification.token, options["reason"])

        print("Email sent successfully (delayed task)")
