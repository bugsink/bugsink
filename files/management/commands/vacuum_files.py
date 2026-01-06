from django.core.management.base import BaseCommand
from files.tasks import vacuum_files


class Command(BaseCommand):
    help = "Kick off (sourcemaps-)files cleanup by vacuuming old entries."

    def handle(self, *args, **options):
        vacuum_files.delay()
        self.stdout.write("Called vacuum_files.delay(); the task will run in the background (snappea).")
