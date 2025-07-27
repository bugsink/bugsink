from django.urls import reverse

from snappea.decorators import shared_task

from bugsink.app_settings import get_settings
from bugsink.utils import send_rendered_email
from bugsink.transaction import immediate_atomic, delay_on_commit
from bugsink.utils import get_model_topography, delete_deps_with_budget


@shared_task
def send_project_invite_email_new_user(email, project_pk, token):
    from .models import Project   # avoid circular import
    project = Project.objects.get(pk=project_pk)

    send_rendered_email(
        subject='You have been invited to join "%s"' % project.name,
        base_template_name="mails/project_membership_invite_new_user",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "project_name": project.name,
            "url": get_settings().BASE_URL + reverse("project_members_accept_new_user", kwargs={
                "token": token,
                "project_pk": project_pk,
            }),
        },
    )


@shared_task
def send_project_invite_email(email, project_pk):
    from .models import Project   # avoid circular import
    project = Project.objects.get(pk=project_pk)

    send_rendered_email(
        subject='You have been invited to join "%s"' % project.name,
        base_template_name="mails/project_membership_invite",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "project_name": project.name,
            "url": get_settings().BASE_URL + reverse("project_members_accept", kwargs={
                "project_pk": project_pk,
            }),
        },
    )


def get_model_topography_with_project_override():
    """
    Returns the model topography with ordering adjusted to prefer deletions via .project, when available.

    This assumes that Project is not only the root of the dependency graph, but also that if a model has an .project
    ForeignKey, deleting it via that path is sufficient, meaning we can safely avoid visiting the same model again
    through other ForeignKey routes (e.g. any of the .issue paths).

    The preference is encoded via an explicit list of models, which are visited early and only via their .project path.
    """
    from issues.models import Issue, TurningPoint, Grouping
    from events.models import Event
    from tags.models import IssueTag, EventTag, TagValue, TagKey
    from alerts.models import MessagingServiceConfig
    from releases.models import Release
    from projects.models import ProjectMembership

    preferred = [
        # Tag-related: remove the "depending" models first and the most depended on last.
        EventTag,      # above Event, to avoid deletions via .event
        IssueTag,
        TagValue,
        TagKey,

        TurningPoint,  # above Event, to avoid deletions via .triggering_event
        Event,         # above Grouping, to avoid deletions via .grouping
        Grouping,

        # these things "could be anywhere" in the ordering; they're not that connected; we put them at the end.
        MessagingServiceConfig,
        ProjectMembership,
        Release,

        Issue,         # at the bottom, most everything points to this, we'd rather delete those things via .project
    ]

    def as_preferred(lst):
        """
        Sorts the list of (model, fk_name) tuples such that the models are in the preferred order as indicated above,
        and models which occur with another fk_name are pruned
        """
        return sorted(
            [(model, fk_name) for model, fk_name in lst if fk_name == "project" or model not in preferred],
            key=lambda x: preferred.index(x[0]) if x[0] in preferred else len(preferred),
        )

    topo = get_model_topography()
    for k, lst in topo.items():
        topo[k] = as_preferred(lst)

    return topo


@shared_task
def delete_project_deps(project_id):
    from .models import Project   # avoid circular import
    with immediate_atomic():
        # matches what we do in events/retention.py (and for which argumentation exists); in practive I have seen _much_
        # faster deletion times (in the order of .03s per task on my local laptop) when using a budget of 500, _but_
        # it's not a given those were for "expensive objects" (e.g. events); and I'd rather err on the side of caution
        # (worst case we have a bit of inefficiency; in any case this avoids hogging the global write lock / timeouts).
        budget = 500
        num_deleted = 0

        dep_graph = get_model_topography_with_project_override()

        for model_for_recursion, fk_name_for_recursion in dep_graph["projects.Project"]:
            this_num_deleted = delete_deps_with_budget(
                project_id,
                model_for_recursion,
                fk_name_for_recursion,
                [project_id],
                budget - num_deleted,
                dep_graph,
                is_for_project=True,
            )

            num_deleted += this_num_deleted

            if num_deleted >= budget:
                delay_on_commit(delete_project_deps, project_id)
                return

        if budget - num_deleted <= 0:
            # no more budget for the self-delete.
            delay_on_commit(delete_project_deps, project_id)

        else:
            # final step: delete the issue itself
            Project.objects.filter(pk=project_id).delete()
