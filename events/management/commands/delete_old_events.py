from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from bugsink.app_settings import get_settings
from events.tasks import delete_events_older_than_sync
from projects.models import Project


class Command(BaseCommand):
    help = "Delete events older than a hard maximum age. Runs 'sync' (waits for completion)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, help="Delete events with digested_at older than this many days.")
        parser.add_argument("--project-id", type=int, help="Only process a single project.")

    def handle(self, *args, **options):
        days = options["days"]
        if days is None:
            days = get_settings().MAX_EVENT_AGE_DAYS

        if days is None:
            raise CommandError("--days is required when MAX_EVENT_AGE_DAYS is not configured.")

        if days < 0:
            raise CommandError("--days must be 0 or greater.")

        cutoff = timezone.now() - timedelta(days=days)
        self.stdout.write(f"Deleting events with digested_at before {cutoff.isoformat()} ({days} days).")

        project_id = options["project_id"]
        if project_id is not None:
            if not Project.objects.filter(pk=project_id).exists():
                raise CommandError(f"Project {project_id} does not exist.")
        total_deleted, total_batches, project_summaries = delete_events_older_than_sync(
            cutoff=cutoff,
            project_id=project_id,
            on_batch=lambda project_id, deleted, project_batches: self.stdout.write(
                f"Project {project_id}: deleted {deleted} events in batch {project_batches}."
            ),
        )

        for project_id, project_deleted, project_batches in project_summaries:
            if project_batches > 0:
                self.stdout.write(
                    f"Project {project_id}: done after {project_batches} batches, deleted {project_deleted}."
                )
            elif options["project_id"] is not None:
                self.stdout.write(f"Project {project_id}: no events matched the age cutoff.")

        self.stdout.write(f"Done: deleted {total_deleted} events in {total_batches} batches.")
