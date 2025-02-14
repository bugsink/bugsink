from django.core.management.base import BaseCommand
from django.db.models import Count

from releases.models import Release
from issues.models import Issue, Grouping, TurningPoint
from events.models import Event
from projects.models import Project


def make_consistent():
    # Delete all issues that have no events; they should not exist and in fact break various templates and views
    for issue in Issue.objects.annotate(fresh_event_count=Count('event')).filter(fresh_event_count=0):
        print("Deleting issue %s, because it has 0 events" % issue)
        issue.delete()

    # Cleanup of dangling stuff (e.g. events without issues); not harmful, but not useful either
    for issue in Issue.objects.filter(project=None):
        print("Deleting issue %s, because it has no project" % issue)
        issue.delete()

    for grouping in Grouping.objects.filter(project=None):
        print("Deleting grouping %s, because it has no project" % grouping)
        grouping.delete()

    for grouping in Grouping.objects.filter(issue=None):
        print("Deleting grouping %s, because it has no issue" % grouping)
        grouping.delete()

    for turning_point in TurningPoint.objects.filter(issue=None):
        print("Deleting turning point %s, because it has no issue" % turning_point)
        turning_point.delete()

    for release in Release.objects.filter(project=None):
        print("Deleting release %s, because it has no project" % release)
        release.delete()

    for event in Event.objects.filter(issue=None):
        print("Deleting event %s, because it has no issue" % event)
        event.delete()

    for event in Event.objects.filter(project=None):
        print("Deleting event %s, because it has no project" % event)
        event.delete()

    for event in Event.objects.filter(turningpoint__isnull=False, never_evict=False).distinct():
        print("Setting event %s to never_evict because it has a turningpoint" % event)
        event.never_evict = True
        event.save()

    # counter reset: do it last, because the above deletions may have changed the counts
    for issue in Issue.objects.all():
        if issue.stored_event_count != issue.event_set.count():
            print("Updating event count for issue %s from %d to %d" % (
                issue, issue.stored_event_count, issue.event_set.count()))
            issue.stored_event_count = issue.event_set.count()
            issue.save()

    for project in Project.objects.all():
        if project.stored_event_count != project.event_set.count():
            print("Updating event count for project %s from %d to %d" % (
                project, project.stored_event_count, project.event_set.count()))
            project.stored_event_count = project.event_set.count()
            project.save()


class Command(BaseCommand):
    help = """In 'normal operation', this command should not be used, because normal operation leaves the DB in a
consistent state. However, during development all bets are off, and to get back to sanity this command may be used."""

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        make_consistent()
