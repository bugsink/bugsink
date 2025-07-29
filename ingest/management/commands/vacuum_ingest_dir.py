import os
import re
import time

from django.core.management.base import BaseCommand, CommandError

from bugsink.app_settings import get_settings


class Command(BaseCommand):
    help = "Clean up old files from the ingest directory. Removes files older than specified days (default: 7)."

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
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']

        if days < 0:
            raise CommandError("Days must be a non-negative number")

        ingest_dir = get_settings().INGEST_STORE_BASE_DIR

        if not os.path.exists(ingest_dir):
            self.stdout.write("Ingest directory does not exist: {}".format(ingest_dir))
            return

        # Calculate cutoff time (files older than this will be removed)
        cutoff_time = time.time() - (days * 24 * 60 * 60)

        # Pattern for valid event IDs (32-character hex strings)
        event_id_pattern = re.compile(r'^[0-9a-f]{32}$')

        files_processed = 0
        files_removed = 0
        unexpected_files = []

        try:
            for filename in os.listdir(ingest_dir):
                filepath = os.path.join(ingest_dir, filename)

                # Skip directories
                if os.path.isdir(filepath):
                    continue

                files_processed += 1

                # Check if filename matches expected event ID format
                if not event_id_pattern.match(filename):
                    unexpected_files.append(filename)
                    continue

                # Check file age
                try:
                    file_mtime = os.path.getmtime(filepath)
                    if file_mtime < cutoff_time:
                        age_days = (time.time() - file_mtime) / (24 * 60 * 60)
                        if dry_run:
                            self.stdout.write("Would remove: {} (age: {:.1f} days)".format(filename, age_days))
                        else:
                            os.remove(filepath)
                            self.stdout.write("Removed: {} (age: {:.1f} days)".format(filename, age_days))
                        files_removed += 1
                except OSError as e:
                    self.stderr.write("Error processing {}: {}".format(filename, e))

        except OSError as e:
            raise CommandError("Error accessing ingest directory {}: {}".format(ingest_dir, e))

        # Report results
        if dry_run:
            self.stdout.write("\nDry run completed:")
        else:
            self.stdout.write("\nCleanup completed:")

        self.stdout.write("  Files processed: {}".format(files_processed))
        self.stdout.write("  Files {}: {}".format('would be removed' if dry_run else 'removed', files_removed))

        if unexpected_files:
            self.stdout.write("  Unexpected files found (skipped): {}".format(len(unexpected_files)))
            for filename in unexpected_files:
                self.stdout.write("    - {}".format(filename))
            self.stdout.write(
                "  Warning: Found files that don't match expected event ID format. "
                "These files were not touched to avoid accidental deletion."
            )
