from django.db.models import Count
from snappea.decorators import shared_task

from bugsink.utils import get_model_topography, delete_deps_with_budget
from bugsink.transaction import immediate_atomic, delay_on_commit


@shared_task
def delete_event_deps(project_id, event_id):
    from .models import Event   # avoid circular import
    with immediate_atomic():
        # matches what we do in events/retention.py (and for which argumentation exists); in practive I have seen _much_
        # faster deletion times (in the order of .03s per task on my local laptop) when using a budget of 500, _but_
        # it's not a given those were for "expensive objects" (e.g. events); and I'd rather err on the side of caution
        # (worst case we have a bit of inefficiency; in any case this avoids hogging the global write lock / timeouts).
        budget = 500
        num_deleted = 0

        # NOTE: for this delete_x_deps, we didn't bother optimizing the topography graph (the dependency-graph of a
        # single event is believed to be small enough to not warrent further optimization).
        dep_graph = get_model_topography()

        for model_for_recursion, fk_name_for_recursion in dep_graph["events.Event"]:
            this_num_deleted = delete_deps_with_budget(
                project_id,
                model_for_recursion,
                fk_name_for_recursion,
                [event_id],
                budget - num_deleted,
                dep_graph,
                is_for_project=False,
            )

            num_deleted += this_num_deleted

            if num_deleted >= budget:
                delay_on_commit(delete_event_deps, project_id, event_id)
                return

        if budget - num_deleted <= 0:
            # no more budget for the self-delete.
            delay_on_commit(delete_event_deps, project_id, event_id)

        else:
            # final step: delete the event itself
            issue = Event.objects.get(pk=event_id).issue

            Event.objects.filter(pk=event_id).delete()

            # issue.stored_event_count is manually decremented here instead of via delete_deps_with_budget's internal
            # do_pre_delete mechanism because the counter updating there only decs project.stored_event_count.
            # (it was built around Issue-deletion initially, so Issue outliving the event-deletion was not part of that
            # functionality). we might refactor this at some point.
            issue.stored_event_count -= 1
            issue.save(update_fields=["stored_event_count"])


@shared_task
def delete_by_age_until_under_retention_max(project_id):
    # quick and dirty copy/paste from various sources, mainly based on events/retention.py (eviction). _however_, I
    # found that for a 250K event project, the eviction algorithm took ~120s per 500 events deleted (hogging the DB).
    # the present command is much simpler; and runs in ~1s per 500 events deleted on the same VM/dataset.

    from .models import Event   # avoid circular import
    from tags.models import EventTag
    from projects.models import Project
    from issues.models import TurningPoint

    with immediate_atomic():
        project = Project.objects.get(pk=project_id)

        how_many_too_many = max(project.stored_event_count - project.get_retention_max_event_count(), 0)
        if how_many_too_many == 0:
            return

        max_event_count = min(how_many_too_many, 500)

        pks_to_delete = list(Event.objects.filter(
            project_id=project_id).order_by("digested_at")[:max_event_count].values_list("id", flat=True))

        # section lifted from events/retention.py
        from events.retention import cleanup_events_on_storage, EvictionCounts

        # we assume "include_never_evict" here; we'll just take the blunt approach for this task/command
        TurningPoint.objects.filter(triggering_event_id__in=pks_to_delete).update(triggering_event=None)

        # this block is verbatim
        if len(pks_to_delete) > 0:
            cleanup_events_on_storage(
                Event.objects.filter(pk__in=pks_to_delete).exclude(storage_backend=None)
                .values_list("id", "storage_backend")
            )
            deletions_per_issue = {
                d['issue_id']: d['count'] for d in
                Event.objects.filter(pk__in=pks_to_delete).values("issue_id").annotate(count=Count("issue_id"))}

            EventTag.objects.filter(event_id__in=pks_to_delete).delete()
            nr_of_deletions = Event.objects.filter(pk__in=pks_to_delete).delete()[1].get("events.Event", 0)
        else:
            nr_of_deletions = 0
            deletions_per_issue = {}

        evicted = EvictionCounts(nr_of_deletions, deletions_per_issue)

        # based on ingest/views.py
        from ingest.views import update_issue_counts
        update_issue_counts(evicted.per_issue)
        project.stored_event_count = project.stored_event_count - evicted.total
        project.save()

        # no conditional here; we just rely on the check at the start
        delay_on_commit(delete_by_age_until_under_retention_max, project_id)
