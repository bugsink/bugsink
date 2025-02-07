from django.core.management.base import BaseCommand

from bugsink.transaction import durable_atomic
from snappea.models import Task
from events.models import Event


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            "stat",
            choices=[
                "snappea-queue-size",
                "event_count",
            ],
        )

    def handle(self, *args, **options):
        stat = options["stat"]

        if stat == "snappea-queue-size":
            print(Task.objects.all().count())

        if stat == "event_count":
            with durable_atomic():
                print(Event.objects.all().count())
