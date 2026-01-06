from django.core.management.base import BaseCommand
from tags.tasks import vacuum_tagvalues


class Command(BaseCommand):
    help = "Kick off tag cleanup by vacuuming orphaned TagValue and TagKey entries."

    def handle(self, *args, **options):
        vacuum_tagvalues.delay()
        self.stdout.write("Called vacuum_tagvalues.delay(); the task will run in the background (snappea).")
