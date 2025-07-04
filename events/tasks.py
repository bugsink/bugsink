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

            # manual (outside of delete_deps_with_budget) b/c the special-case in that function is (ATM) specific to
            # project (it was built around Issue-deletion initially, so Issue outliving the event-deletion was not
            # part of that functionality). we might refactor this at some point.
            issue.stored_event_count -= 1
            issue.save(update_fields=["stored_event_count"])
