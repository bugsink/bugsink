from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Calls `migrate` with `check_unapplied=True` to check for unapplied migrations (2 DBs, adds error message)"

    def handle(self, *args, **options):
        try:
            call_command('migrate', check_unapplied=True)
        except SystemExit:
            self.stdout.write(self.style.ERROR(
                "You have unapplied migrations. Make sure to call `bugsink-manage migrate` before running the server."
            ))
            raise

        try:
            call_command('migrate', "snappea", check_unapplied=True, database="snappea")
        except SystemExit:
            self.stdout.write(self.style.ERROR(
                "You have unapplied migrations. Make sure to call `bugsink-manage migrate snappea --database=snappea` "
                "before running the server."
            ))
            raise
