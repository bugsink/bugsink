from django.core.management.base import BaseCommand

from snappea.models import Task


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            "stat",
            choices=["snappea-queue-size"],
        )

    def handle(self, *args, **options):
        stat = options["stat"]

        if stat == "snappea-queue-size":
            print(Task.objects.all().count())
