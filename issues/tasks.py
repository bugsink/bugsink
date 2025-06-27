from snappea.decorators import shared_task

from bugsink.utils import get_model_topography, delete_deps_with_budget
from bugsink.transaction import immediate_atomic, delay_on_commit


@shared_task
def delete_issue_deps(issue_id):
    from .models import Issue   # avoid circular import
    with immediate_atomic():
        budget = 500
        num_deleted = 0

        dep_graph = get_model_topography()

        for model_for_recursion, fk_name_for_recursion in dep_graph["issues.Issue"]:
            this_num_deleted = delete_deps_with_budget(
                model_for_recursion,
                fk_name_for_recursion,
                [issue_id],
                budget - num_deleted,
                dep_graph,
            )

            num_deleted += this_num_deleted

            if num_deleted >= budget:
                delay_on_commit(delete_issue_deps, issue_id)
                return

        if budget - num_deleted <= 0:
            # no more budget for the self-delete.
            delay_on_commit(delete_issue_deps, issue_id)

        else:
            # final step: delete the issue itself
            Issue.objects.filter(pk=issue_id).delete()
