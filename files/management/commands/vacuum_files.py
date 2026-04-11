from django.core.management.base import BaseCommand

from bugsink.app_settings import get_settings
from files.tasks import vacuum_files


class Command(BaseCommand):
    help = "Kick off (async, in snappea) (sourcemaps-)files cleanup by vacuuming old entries."

    def add_arguments(self, parser):
        # default of chunk_max_days=1 is already quite long... Chunks are used immediately, or not at all.
        parser.add_argument(
            '--chunk-max-days', type=int, default=1,
            help="Delete Chunk objects older than this many days (default: 1).")

        parser.add_argument(
            '--file-max-days', type=int, default=90,
            help="Delete File objects not accessed for more than this many days (default: 90).")
        parser.add_argument(
            '--max-file-count', type=int,
            help="Keep at most this many stored File objects site-wide. Defaults to MAX_STORED_FILE_COUNT.")
        parser.add_argument(
            '--max-file-bytes', type=int,
            help="Keep at most this many bytes across stored File objects. Defaults to MAX_STORED_FILE_BYTES.")

    def handle(self, *args, **options):
        settings = get_settings()
        max_file_count = options['max_file_count']
        max_file_bytes = options['max_file_bytes']

        vacuum_files.delay(
            chunk_max_days=options['chunk_max_days'],
            file_max_days=options['file_max_days'],
            max_file_count=settings.MAX_STORED_FILE_COUNT if max_file_count is None else max_file_count,
            max_file_bytes=settings.MAX_STORED_FILE_BYTES if max_file_bytes is None else max_file_bytes,
        )
        self.stdout.write("Called vacuum_files.delay(); the task will run in the background (snappea).")
