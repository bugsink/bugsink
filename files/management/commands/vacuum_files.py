from django.core.management.base import BaseCommand
from files.tasks import vacuum_files


class Command(BaseCommand):
    help = "Kick off (sourcemaps-)files cleanup by vacuuming old entries."

    def add_arguments(self, parser):
        parser.add_argument(
            '--chunk-max-days', type=int, default=1,
            help="Delete Chunk objects older than this many days (default: 1).")
        parser.add_argument(
            '--file-max-days', type=int, default=90,
            help="Delete File objects not accessed for more than this many days (default: 90).")

    def handle(self, *args, **options):
        vacuum_files.delay(chunk_max_days=options['chunk_max_days'], file_max_days=options['file_max_days'])
        self.stdout.write("Called vacuum_files.delay(); the task will run in the background (snappea).")
