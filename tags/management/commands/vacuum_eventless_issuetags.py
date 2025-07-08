from django.core.management.base import BaseCommand
from tags.tasks import vacuum_eventless_issuetags


class Command(BaseCommand):
    help = "Kick off tag cleanup by vacuuming IssueTag objects for which there is no EventTag equivalent"

    def handle(self, *args, **options):
        vacuum_eventless_issuetags.delay()
        self.stdout.write("Started tag vacuum via task queue.")
