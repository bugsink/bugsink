import os

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from phonehome.tasks import send_if_due


User = get_user_model()


class Command(BaseCommand):
    help = "Pre-start command to run before the server starts."

    def _create_superuser_if_needed(self):
        if not os.getenv("CREATE_SUPERUSER", ""):
            return

        if ":" not in os.getenv("CREATE_SUPERUSER"):
            raise ValueError("CREATE_SUPERUSER should be in the format 'username:password'")

        username, password = os.getenv("CREATE_SUPERUSER").split(":")

        if User.objects.all().exists():
            print(
                "Superuser not created: _any_ user(s) already exist(s). "
                "CREATE_SUPERUSER only works for the initial user.")

            return

        User.objects.create_superuser(username=username, password=password)
        print(f"Superuser created: {username}")

    def handle(self, *args, **options):
        self._create_superuser_if_needed()

        # Similar considerations apply here as those which are documented in bugsink.views._phone_home().
        # By putting this in prestart, we add one more location to the list of kick-off locations; with the added
        # benefit that this particular location also gives some signal for (Docker) installations that are prematurely
        # aborted (i.e. we get a ping even if 'home' is never even reached).
        send_if_due.delay()
