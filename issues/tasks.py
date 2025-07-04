from snappea.decorators import shared_task

from bugsink.utils import get_model_topography, delete_deps_with_budget
from bugsink.transaction import immediate_atomic, delay_on_commit


def get_model_topography_with_issue_override():
    """
    Returns the model topography with ordering adjusted to prefer deletions via .issue, when available.

    This assumes that Issue is not only the root of the dependency graph, but also that if a model has an .issue
    ForeignKey, deleting it via that path is sufficient, meaning we can safely avoid visiting the same model again
    through other ForeignKey routes (e.g. Event.grouping or TurningPoint.triggering_event).

    The preference is encoded via an explicit list of models, which are visited early and only via their .issue path.
    """
    from issues.models import TurningPoint, Grouping
    from events.models import Event
    from tags.models import IssueTag, EventTag

    preferred = [
        TurningPoint,  # above Event, to avoid deletions via .triggering_event
        EventTag,      # above Event, to avoid deletions via .event
        Event,         # above Grouping, to avoid deletions via .grouping
        Grouping,
        IssueTag,
    ]

    def as_preferred(lst):
        """
        Sorts the list of (model, fk_name) tuples such that the models are in the preferred order as indicated above,
        and models which occur with another fk_name are pruned
        """
        return sorted(
            [(model, fk_name) for model, fk_name in lst if fk_name == "issue" or model not in preferred],
            key=lambda x: preferred.index(x[0]) if x[0] in preferred else len(preferred),
        )

    topo = get_model_topography()
    for k, lst in topo.items():
        topo[k] = as_preferred(lst)

    return topo


@shared_task
def delete_issue_deps(project_id, issue_id):
    from .models import Issue   # avoid circular import
    with immediate_atomic():
        # matches what we do in events/retention.py (and for which argumentation exists); in practive I have seen _much_
        # faster deletion times (in the order of .03s per task on my local laptop) when using a budget of 500, _but_
        # it's not a given those were for "expensive objects" (e.g. events); and I'd rather err on the side of caution
        # (worst case we have a bit of inefficiency; in any case this avoids hogging the global write lock / timeouts).
        budget = 500
        num_deleted = 0

        dep_graph = get_model_topography_with_issue_override()

        for model_for_recursion, fk_name_for_recursion in dep_graph["issues.Issue"]:
            this_num_deleted = delete_deps_with_budget(
                project_id,
                model_for_recursion,
                fk_name_for_recursion,
                [issue_id],
                budget - num_deleted,
                dep_graph,
                is_for_project=False,
            )

            num_deleted += this_num_deleted

            if num_deleted >= budget:
                delay_on_commit(delete_issue_deps, project_id, issue_id)
                return

        if budget - num_deleted <= 0:
            # no more budget for the self-delete.
            delay_on_commit(delete_issue_deps, project_id, issue_id)

        else:
            # final step: delete the issue itself
            Issue.objects.filter(pk=issue_id).delete()
