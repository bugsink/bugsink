from django.core.management.base import BaseCommand

from bsmain.models import AuthToken
from bugsink.transaction import immediate_atomic


class Command(BaseCommand):
    help = "Creates an auth_token and prints it on screen"""

    def handle(self, *args, **options):
        with immediate_atomic():
            auth_token = AuthToken.create_full_access()
        print(auth_token.token)
