from django.core.management.base import BaseCommand

from snappea.example_tasks import fast_task


class Command(BaseCommand):
    help = "Send a task to Snappea for debugging"

    def handle(self, *args, **options):
        print("Sending task to Snappea")
        fast_task.delay()
