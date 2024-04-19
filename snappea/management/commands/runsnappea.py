from django.core.management.base import BaseCommand

from snappea.foreman import Foreman


class Command(BaseCommand):
    help = "Run the SnapPea foreman service."

    def handle(self, *args, **options):
        Foreman().run_forever()
