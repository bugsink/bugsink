from django.core.management.base import BaseCommand

from snappea.models import Task


class Command(BaseCommand):
    # "ingest" may not be the best place for this, but "bugsink" is not an app, so Django won't discover it.

    def add_arguments(self, parser):
        parser.add_argument(
            "stat",
            choices=["snappea-queue-size"],
        )

    def handle(self, *args, **options):
        stat = options["stat"]

        if stat == "snappea-queue-size":
            print(Task.objects.all().count())
