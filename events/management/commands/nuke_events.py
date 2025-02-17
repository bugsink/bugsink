from django.core.management.base import BaseCommand

from bugsink.app_settings import get_settings

from issues.models import Issue, TurningPoint, Grouping
from events.models import Event
from events.management.commands.make_consistent import make_consistent

from bugsink.transaction import immediate_atomic
from bugsink.timed_sqlite_backend.base import allow_long_running_queries


class Command(BaseCommand):
    help = "Throw away all events and issues, preserve teams, projects and users."

    def handle(self, *args, **options):
        allow_long_running_queries()
        if not input("""This will complete REMOVE ALL ISSUES and EVENTS on %s.

Are you sure? (yes/no) """ % get_settings().BASE_URL).lower().startswith("y"):

            print("Aborted.")
            return

        with immediate_atomic():
            # Turningpoints are deleted first because they have a ForeignKey to Event (without SET_NULL/CASCADE)
            print("Deleted", TurningPoint.objects.all().delete()[1].get("issues.TurningPoint", 0), "turning points.")
            print("Deleted", Event.objects.all().delete()[1].get("events.Event", 0), "events.")
            print("Deleted", Grouping.objects.all().delete()[1].get("issues.Grouping", 0), "groupings.")
            print("Deleted", Issue.objects.all().delete()[1].get("issues.Issue", 0), "issues.")

            print()
            print("Now running make_consistent to get back to a consistent state...")

            make_consistent()
