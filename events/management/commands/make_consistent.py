from django.core.management.base import BaseCommand
from django.db.models import Count

from releases.models import Release
from issues.models import Issue
from events.models import Event


def make_consistent():
    # Delete all issues that have no events; they should not exist and in fact break various templates and views
    for issue in Issue.objects.annotate(fresh_event_count=Count('event')).filter(fresh_event_count=0):
        print("Deleting issue %s, because it has 0 events" % issue)
        issue.delete()

    # Cleanup of dangling stuff (e.g. events without issues); not harmful, but not useful either
    for issue in Issue.objects.filter(project=None):
        print("Deleting issue %s, because it has no project" % issue)
        issue.delete()

    for release in Release.objects.filter(project=None):
        print("Deleting release %s, because it has no project" % release)
        release.delete()

    for event in Event.objects.filter(issue=None):
        print("Deleting event %s, because it has no issue" % event)
        event.delete()

    for event in Event.objects.filter(project=None):
        print("Deleting event %s, because it has no project" % event)
        event.delete()


class Command(BaseCommand):
    help = """In 'normal operation', this command should not be used, because normal operation leaves the DB in a
consistent state. However, during development all bets are off, and to get back to sanity this command may be used."""

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        make_consistent()
