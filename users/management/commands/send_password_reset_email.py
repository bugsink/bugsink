from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from users.models import EmailVerification
from users.tasks import send_reset_email

UserModel = get_user_model()


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, required=True)

    def handle(self, *args, **options):
        email = options["email"]
        user = UserModel.objects.get(email=email)

        # copy/paste from views.py (excluding the comments)
        verification = EmailVerification.objects.create(user=user, email=user.username)
        send_reset_email.delay(user.username, verification.token)

        print("Email sent successfully (delayed task)")
