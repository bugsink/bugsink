import json
from django.core.management.base import BaseCommand

from phonehome.tasks import _make_message_body


class Command(BaseCommand):
    help = "Print the phonehome message to the console."

    def handle(self, *args, **options):
        message_body = _make_message_body()
        print(json.dumps(message_body, indent=4))
