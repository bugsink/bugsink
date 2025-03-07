from django.core.management.base import BaseCommand
from django.db.models import Count

from releases.models import Release
from issues.models import Issue, Grouping, TurningPoint
from events.models import Event
from projects.models import Project
from tags.models import TagKey, TagValue, EventTag, IssueTag

from bugsink.transaction import immediate_atomic
from bugsink.timed_sqlite_backend.base import allow_long_running_queries
from bugsink.moreiterutils import batched


class DryRunException(Exception):
    # transaction.rollback doesn't work in atomic blocks; a poor man's substitute is to just raise something specific.
    pass


def _delete_for_missing_fk(clazz, field_name):
    """
    Delete all objects of class clazz of which the field field_name points to a non-existing object or null.

    ## Dangling FKs:
    Non-existing objects may come into being when people muddle in the database directly with foreign key checks turned
    off (note that fk checks are turned off by default in SQLite for backwards compatibility reasons).

    In the future it's further possible that there will be pieces the actual Bugsink code where FK-checks are turned off
    temporarily (e.g. when deleting a project with very many related objects). (In March 2025 there was no such code
    yet)

    To make make_consistent() do what it says on the can, we need to delete these dangling objects.
    """
    BATCH_SIZE = 1_000

    dangling_fks = set()

    field = clazz._meta.get_field(field_name)
    related_model = field.related_model

    # We just load _all_ available PKs into memory; it's expected that environments with millions of records will
    # have enough RAM to deal with this (millions would translate into ~Gigabytes of RAM).
    available_keys = set(related_model.objects.values_list('pk', flat=True))

    # construct "dangling_fks"
    for batch in batched(clazz.objects.values_list(field.get_attname(), flat=True).distinct(), BATCH_SIZE):
        for key in batch:
            if key not in available_keys:
                dangling_fks.add(key)

    def _del(deletion_kwargs, msg_kind):
        total_cnt, d_of_counts = clazz.objects.filter(**deletion_kwargs).delete()
        count = d_of_counts.get(clazz._meta.label, 0)
        if count == 0:
            return
        print("Deleted %d %ss, because their %s was %s" % (count, clazz.__name__, field_name, msg_kind))

    _del({field.get_attname(): None}, "NULL")
    for batch in batched(dangling_fks, BATCH_SIZE):
        _del({field.get_attname() + '__in': batch}, "non-existing")


def make_consistent():
    # Delete all issues that have no events; they should not exist and in fact break various templates and views
    for issue in Issue.objects.annotate(fresh_event_count=Count('event')).filter(fresh_event_count=0):
        print("Deleting issue %s, because it has 0 events" % issue)
        issue.delete()

    # Various "dangling pointer" deletions:
    _delete_for_missing_fk(Issue, 'project')

    _delete_for_missing_fk(Grouping, 'project')
    _delete_for_missing_fk(Grouping, 'issue')

    _delete_for_missing_fk(TurningPoint, 'issue')

    _delete_for_missing_fk(Release, 'project')

    _delete_for_missing_fk(Event, 'project')
    _delete_for_missing_fk(Event, 'issue')

    _delete_for_missing_fk(IssueTag, 'project')
    _delete_for_missing_fk(IssueTag, 'value')
    _delete_for_missing_fk(IssueTag, 'issue')

    _delete_for_missing_fk(EventTag, 'project')
    _delete_for_missing_fk(EventTag, 'value')
    _delete_for_missing_fk(EventTag, 'event')

    _delete_for_missing_fk(TagValue, 'project')
    _delete_for_missing_fk(TagValue, 'key')

    _delete_for_missing_fk(TagKey, 'project')

    for event in Event.objects.filter(turningpoint__isnull=False, never_evict=False).distinct():
        print("Setting event %s to never_evict because it has a turningpoint" % event)
        event.never_evict = True
        event.save()

    # Update counters
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

    # Alternatively (but does it work in MySQL?)
    # Issue.objects.update(
    #     stored_event_count=Subquery(
    #         Issue.objects.filter(pk=OuterRef('pk')).annotate(recount=Count('event')).values('recount')[:1])
    # )

    # Project.objects.update(
    #     stored_event_count=Subquery(
    #         Project.objects.filter(pk=OuterRef('pk')).annotate(recount=Count('event')).values('recount')[:1])
    # )

    # Update Project.has_releases

    for project in Project.objects.all():
        if project.has_releases != project.release_set.exists():
            print("Updating has_releases for project %s from %s to %s" % (
                project, project.has_releases, project.release_set.exists()))
            project.has_releases = project.release_set.exists()
            project.save()


class Command(BaseCommand):
    help = """Make the database consistent by deleting dangling objects (issues, events, etc) and updating counters."""

    # In theory, this command should not be required, because Bugsink _should_ leave itself in a consistent state after
    # every operation. However, in practice Bugsink may not always do as promised, people reach into the database for
    # whatever reason, or things go out of whack during development.

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Roll back all changes after making them.")

    def handle(self, *args, **options):
        allow_long_running_queries()

        try:
            with immediate_atomic():
                make_consistent()
                if options['dry_run']:
                    raise DryRunException("Dry run requested; rolling back changes.")
        except DryRunException:
            print("Changes have been rolled back (dry-run)")
