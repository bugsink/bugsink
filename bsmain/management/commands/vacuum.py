from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from bugsink.app_settings import get_settings
from events.tasks import delete_events_older_than_sync
from files.tasks import vacuum_files_sync
from ingest.management.commands.vacuum_ingest_dir import vacuum_ingest_dir_sync
from issues.tasks import delete_marked_issues_sync, mark_orphaned_issues_sync
from tags.tasks import vacuum_eventless_issuetags_sync, vacuum_tags_sync


class Command(BaseCommand):
    help = "Vacuum old/stale data. Single point of entry for all vacuum_* tasks. Runs 'sync' (waits for completion)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--files',
            action='store_true',
            help="Run old file and chunk cleanup.",
        )
        parser.add_argument(
            '--tags',
            action='store_true',
            help="Run orphaned TagValue and TagKey cleanup.",
        )
        parser.add_argument(
            '--eventless-issuetags',
            action='store_true',
            help="Run IssueTag cleanup for rows without matching EventTag rows.",
        )
        parser.add_argument(
            '--old-events',
            action='store_true',
            help="Delete events older than the configured maximum age.",
        )
        parser.add_argument(
            '--ingest-dir',
            action='store_true',
            help="Clean up stale files from the ingest directory.",
        )
        parser.add_argument(
            '--deleted-issues',
            action='store_true',
            help="Finish deleting issues already marked for deletion.",
        )
        parser.add_argument(
            '--orphaned-issues',
            action='store_true',
            help="Delete issues without stored events. Not included by default.",
        )
        parser.add_argument(
            '--chunk-max-days',
            type=int,
            default=1,
            help="Delete Chunk objects older than this many days (default: 1).",
        )
        parser.add_argument(
            '--file-max-days',
            type=int,
            default=90,
            help="Delete File objects not accessed for more than this many days (default: 90).",
        )
        parser.add_argument(
            '--max-event-age-days',
            type=int,
            help="Delete events with digested_at older than this many days.",
        )
        parser.add_argument(
            '--max-file-count',
            type=int,
            help="Keep at most this many stored File objects site-wide. Defaults to MAX_STORED_FILE_COUNT.",
        )
        parser.add_argument(
            '--max-file-bytes',
            type=int,
            help="Keep at most this many bytes across stored File objects. Defaults to MAX_STORED_FILE_BYTES.",
        )
        parser.add_argument(
            '--ingest-max-days',
            type=int,
            default=7,
            help="Delete ingest-dir files older than this many days (default: 7).",
        )
        parser.add_argument(
            '--orphaned-issue-max-days',
            type=int,
            help="Only delete orphaned issues last seen more than this many days ago.",
        )

    def handle(self, *args, **options):
        run_files = options['files']
        run_tags = options['tags']
        run_eventless_issuetags = options['eventless_issuetags']
        run_old_events = options['old_events']
        run_ingest_dir = options['ingest_dir']
        run_deleted_issues = options['deleted_issues']
        run_orphaned_issues = options['orphaned_issues']

        orphaned_issue_max_days = options["orphaned_issue_max_days"]
        if orphaned_issue_max_days is not None and orphaned_issue_max_days < 0:
            raise CommandError("--orphaned-issue-max-days must be 0 or greater.")

        if not any([
            run_files,
            run_tags,
            run_eventless_issuetags,
            run_old_events,
            run_ingest_dir,
            run_deleted_issues,
            run_orphaned_issues,
        ]):
            # If no specific options were provided, run all vacuum tasks by default, except orphaned issue cleanup,
            # because deleting issues is destructive and must be explicitly requested.
            run_files = True
            run_tags = True
            run_eventless_issuetags = True
            run_old_events = True
            run_ingest_dir = True
            run_deleted_issues = True

        if run_files:
            settings = get_settings()
            max_file_count = options['max_file_count']
            max_file_bytes = options['max_file_bytes']
            self.stdout.write("Vacuuming files...")

            log_progress = self.stdout.write if options["verbosity"] >= 2 else lambda _message: None
            vacuum_files_sync(
                chunk_max_days=options['chunk_max_days'],
                file_max_days=options['file_max_days'],
                max_file_count=settings.MAX_STORED_FILE_COUNT if max_file_count is None else max_file_count,
                max_file_bytes=settings.MAX_STORED_FILE_BYTES if max_file_bytes is None else max_file_bytes,
                log_progress=log_progress,
            )

        if run_old_events:
            self.stdout.write("Vacuuming old events...")
            days = options["max_event_age_days"]
            if days is None:
                days = get_settings().MAX_EVENT_AGE_DAYS

            if days is None:
                self.stdout.write("Skipping old events; MAX_EVENT_AGE_DAYS is not configured.")
            else:
                delete_events_older_than_sync(
                    cutoff=timezone.now() - timedelta(days=days),
                )

        if run_orphaned_issues:
            cutoff = (
                timezone.now() - timedelta(days=orphaned_issue_max_days)
                if orphaned_issue_max_days is not None else None
            )
            self.stdout.write("Vacuuming orphaned issues...")
            mark_orphaned_issues_sync(cutoff)

        if run_orphaned_issues or run_deleted_issues:
            self.stdout.write("Vacuuming deleted issues...")
            delete_marked_issues_sync()

        if run_eventless_issuetags:
            self.stdout.write("Vacuuming eventless issuetags...")
            vacuum_eventless_issuetags_sync()

        if run_tags:
            self.stdout.write("Vacuuming tags...")
            vacuum_tags_sync()

        if run_ingest_dir:
            self.stdout.write("Checking for stale temporary ingest files...")
            vacuum_ingest_dir_sync(days=options["ingest_max_days"], stdout=self.stdout, stderr=self.stderr)

        self.stdout.write(self.style.SUCCESS("Vacuum complete."))
