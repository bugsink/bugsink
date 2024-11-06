import os

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


User = get_user_model()


class Command(BaseCommand):
    help = "Pre-start command to run before the server starts."

    def handle(self, *args, **options):
        if os.getenv("CREATE_SUPERUSER", ""):
            if ":" not in os.getenv("CREATE_SUPERUSER"):
                raise ValueError("CREATE_SUPERUSER should be in the format 'username:password'")

            username, password = os.getenv("CREATE_SUPERUSER").split(":")

            if not User.objects.filter(username=username).exists():
                User.objects.create_superuser(username=username, password=password)
                print(f"Superuser created: {username}")
