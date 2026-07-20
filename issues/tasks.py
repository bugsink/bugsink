from snappea.decorators import shared_task

from bugsink.utils import get_model_topography, delete_deps_with_budget
from bugsink.transaction import immediate_atomic, delay_on_commit


DELETE_ISSUE_DEPS_BATCH_SIZE = 500
MARK_ORPHANED_ISSUES_BATCH_SIZE = 250
DELETE_MARKED_ISSUES_BATCH_SIZE = 250


def get_orphaned_issues(cutoff=None):
    from .models import Issue

    queryset = Issue.objects.filter(is_deleted=False, stored_event_count=0)
    if cutoff is not None:
        queryset = queryset.filter(last_seen__lt=cutoff)
    return queryset


def mark_orphaned_issues_sync(cutoff=None):
    min_issue_id = None
    while True:
        min_issue_id = mark_orphaned_issues_batch(cutoff, min_issue_id)
        if min_issue_id is None:
            return


def mark_orphaned_issues_batch(cutoff=None, min_issue_id=None):
    # Returns the last examined issue ID, or None when there are no candidates left.
    from .models import mark_issues_for_deletion

    with immediate_atomic():
        queryset = get_orphaned_issues(cutoff)
        if min_issue_id is not None:
            queryset = queryset.filter(id__gt=min_issue_id)

        issue_project_pairs = list(
            queryset.order_by("id").values_list("id", "project_id")[:MARK_ORPHANED_ISSUES_BATCH_SIZE]
        )
        if not issue_project_pairs:
            return None

        mark_issues_for_deletion(issue_project_pairs)
        return issue_project_pairs[-1][0]


def delete_marked_issues_sync():
    from .models import Issue

    while True:
        # This selection needs no write transaction: each dependency batch is atomic, and a root deleted after this read
        # is harmless because dependency deletion is idempotent.
        issue_project_pairs = list(
            Issue.objects.filter(is_deleted=True)
            .order_by("id")
            .values_list("id", "project_id")[:DELETE_MARKED_ISSUES_BATCH_SIZE]
        )
        if not issue_project_pairs:
            return

        for issue_id, project_id in issue_project_pairs:
            delete_issue_deps_sync(project_id, issue_id)


def cleanup_orphaned_issues_sync(cutoff=None):
    mark_orphaned_issues_sync(cutoff)
    delete_marked_issues_sync()


def get_model_topography_with_issue_override():
    """
    Returns the model topography with ordering adjusted to prefer deletions via .issue, when available.

    This assumes that Issue is not only the root of the dependency graph, but also that if a model has an .issue
    ForeignKey, deleting it via that path is sufficient, meaning we can safely avoid visiting the same model again
    through other ForeignKey routes (e.g. Event.grouping or TurningPoint.triggering_event).

    The preference is encoded via an explicit list of models, which are visited early and only via their .issue path.
    """
    from issues.models import TurningPoint, Grouping
    from events.models import Event, IssueEventCountsPerHour
    from tags.models import IssueTag, EventTag

    preferred = [
        TurningPoint,  # above Event, to avoid deletions via .triggering_event
        IssueEventCountsPerHour,
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
    if delete_issue_deps_batch(project_id, issue_id):
        delay_on_commit(delete_issue_deps, project_id, issue_id)


def delete_issue_deps_sync(project_id, issue_id):
    while delete_issue_deps_batch(project_id, issue_id):
        pass


def delete_issue_deps_batch(project_id, issue_id):
    # Returns True when the deletion budget was exhausted and another batch is needed.
    from .models import Issue   # avoid circular import
    with immediate_atomic():
        # matches what we do in events/retention.py (and for which argumentation exists); in practive I have seen _much_
        # faster deletion times (in the order of .03s per task on my local laptop) when using a budget of 500, _but_
        # it's not a given those were for "expensive objects" (e.g. events); and I'd rather err on the side of caution
        # (worst case we have a bit of inefficiency; in any case this avoids hogging the global write lock / timeouts).
        num_deleted = 0

        dep_graph = get_model_topography_with_issue_override()

        for model_for_recursion, fk_name_for_recursion in dep_graph["issues.Issue"]:
            this_num_deleted = delete_deps_with_budget(
                project_id,
                model_for_recursion,
                fk_name_for_recursion,
                [issue_id],
                DELETE_ISSUE_DEPS_BATCH_SIZE - num_deleted,
                dep_graph,
                is_for_project=False,
            )

            num_deleted += this_num_deleted

            if num_deleted >= DELETE_ISSUE_DEPS_BATCH_SIZE:
                break

        if DELETE_ISSUE_DEPS_BATCH_SIZE - num_deleted <= 0:
            # no more budget for the self-delete.
            return True

        else:
            # final step: delete the issue itself
            Issue.objects.filter(pk=issue_id).delete()
            return False
