from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from bugsink.app_settings import get_settings
from users.models import EmailVerification


User = get_user_model()


class Command(BaseCommand):
    help = "Creates a set-password link for a user and prints it on screen"

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["email"])
        except User.DoesNotExist as e:
            raise CommandError("No user with this email address exists") from e

        verification = EmailVerification.objects.create(user=user, email=user.username)
        self.stdout.write(get_settings().BASE_URL + reverse("reset_password", kwargs={"token": verification.token}))
