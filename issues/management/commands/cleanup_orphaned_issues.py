from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from issues.tasks import cleanup_orphaned_issues_sync, get_orphaned_issues


class Command(BaseCommand):
    help = "Delete issues without stored events."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, help="Only delete issues last seen more than this many days ago.")
        parser.add_argument("--dry-run", action="store_true", help="Show how many issues would be deleted.")

    def handle(self, *args, **options):
        days = options["days"]
        if days is not None and days < 0:
            raise CommandError("--days must be 0 or greater.")

        cutoff = timezone.now() - timedelta(days=days) if days is not None else None

        if options["dry_run"]:
            candidate_count = get_orphaned_issues(cutoff).count()
            issue_label = "issue" if candidate_count == 1 else "issues"
            self.stdout.write(f"Would delete {candidate_count} orphaned {issue_label}.")
            return

        cleanup_orphaned_issues_sync(cutoff)
        self.stdout.write(self.style.SUCCESS("Orphaned issue cleanup complete."))
