import os
import time
import re
from django.core.management.base import BaseCommand, CommandError
from bugsink.app_settings import get_settings


class Command(BaseCommand):
    help = "Clean up old files from the ingest directory to prevent garbage accumulation"

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Remove files older than this many days (default: 7)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting files'
        )

    def handle(self, *args, **options):
        days = options.get('days', 7)
        dry_run = options.get('dry_run', False)

        if days <= 0:
            raise CommandError("Days must be a positive integer")

        ingest_dir = get_settings().INGEST_STORE_BASE_DIR

        if not os.path.exists(ingest_dir):
            self.stdout.write(f"Ingest directory does not exist: {ingest_dir}")
            return

        # UUID hex pattern: exactly 32 hexadecimal characters
        uuid_hex_pattern = re.compile(r'^[0-9a-f]{32}$')

        cutoff_time = time.time() - (days * 24 * 60 * 60)

        removed_count = 0
        unexpected_files = []

        self.stdout.write(f"Scanning ingest directory: {ingest_dir}")
        self.stdout.write(f"Removing files older than {days} days{' (DRY RUN)' if dry_run else ''}")

        try:
            for filename in os.listdir(ingest_dir):
                filepath = os.path.join(ingest_dir, filename)

                # Skip directories
                if os.path.isdir(filepath):
                    continue

                # Check if filename matches expected UUID hex pattern
                if not uuid_hex_pattern.match(filename):
                    unexpected_files.append(filename)
                    continue

                # Check file age
                try:
                    stat = os.stat(filepath)
                    if stat.st_mtime < cutoff_time:
                        if dry_run:
                            self.stdout.write(f"Would remove: {filename}")
                        else:
                            os.unlink(filepath)
                            self.stdout.write(f"Removed: {filename}")
                        removed_count += 1
                except OSError as e:
                    self.stderr.write(f"Error processing {filename}: {e}")

        except OSError as e:
            raise CommandError(f"Error accessing ingest directory: {e}")

        # Report results
        if unexpected_files:
            self.stdout.write(
                self.style.WARNING(
                    f"Found {len(unexpected_files)} unexpected files (not matching UUID hex pattern):"
                )
            )
            for filename in unexpected_files:
                self.stdout.write(f"  {filename}")
            self.stdout.write("These files were NOT removed for safety.")

        if dry_run:
            self.stdout.write(f"DRY RUN: Would have removed {removed_count} files")
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully removed {removed_count} files")
            )
