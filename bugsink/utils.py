import random
import logging
from collections import defaultdict

from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import get_template
from django.apps import apps
from django.db.models import ForeignKey, F

# imported here to avoid breakage on conf scripts which depend on these 3 utils to be part of .utils (backwards compat)
from .conf_utils import deduce_allowed_hosts, deduce_script_name, eat_your_own_dogfood  # noqa: F401

# alias for the random module that is explicitly used in "non-cryptographic" contexts; this is a utility to avoid false
# positives in (bandit) security scans that complain about the use of `random`; by flagging a use as "non-cryptographic"
# we avoid sprinkling `nosec` (and their explanations) all over the codebase.
nc_rnd = random

logger = logging.getLogger("bugsink.email")


def send_rendered_email(subject, base_template_name, recipient_list, context=None):
    from phonehome.models import Installation

    if not Installation.check_and_inc_email_quota(timezone.now()):
        logger.warning(
            "Email quota exceeded; not sending email with subject '%s' to %s",
            subject,
            recipient_list,
        )
        return

    if context is None:
        context = {}

    html_content = get_template(base_template_name + ".html").render(context)
    text_content = get_template(base_template_name + ".txt").render(context)

    # Configure and send an EmailMultiAlternatives
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,  # this is settings.DEFAULT_FROM_EMAIL
        to=recipient_list,
    )

    msg.attach_alternative(html_content, "text/html")

    msg.send(fail_silently=False)  # (fail_silently=False is the default)


def get_model_topography():
    """
    Returns a dependency graph mapping:
      referenced_model_key -> [
          (referrer_model_class, fk_name),
          ...
      ]
    """
    dep_graph = defaultdict(list)
    for model in apps.get_models():
        for field in model._meta.get_fields(include_hidden=True):
            if isinstance(field, ForeignKey):
                referenced_model = field.related_model
                referenced_key = f"{referenced_model._meta.app_label}.{referenced_model.__name__}"
                dep_graph[referenced_key].append((model, field.name))
    return dep_graph


def fields_for_prune_orphans(model):
    if model.__name__ == "IssueTag":
        return ("value_id",)
    return ()


def prune_orphans(model, d_ids_to_check):
    """For some model, does dangling-model-cleanup.

    In a sense the oposite of delete_deps; delete_deps takes care of deleting the recursive closure of things that point
    to some root. The present function cleans up things that are being pointed to (and, after some other thing is
    deleted, potentially are no longer being pointed to, hence 'orphaned').

    This is the hardcoded edition (IssueTag only); we _could_ try to think about doing this generically based on the
    dependency graph, but it's quite questionably whether a combination of generic & performant is easy to arrive at and
    worth it.

    pruning of TagValue is done "inline" (as opposed to using a GC-like vacuum "later") because, whatever the exact
    performance trade-offs may be, the following holds true:

    1. the inline version is easier to reason about, it "just happens ASAP", and in the context of a given issue;
       vacuum-based has to take into consideration the full DB including non-orphaned values.
    2. repeated work is somewhat minimalized b/c of the IssueTag/EventTag relationship as described in prune_tagvalues.
    """

    from tags.models import prune_tagvalues  # avoid circular import

    if model.__name__ != "IssueTag":
        return  # we only prune IssueTag orphans

    ids_to_check = [d["value_id"] for d in d_ids_to_check]  # d_ids_to_check: mirrors fields_for_prune_orphans(model)

    prune_tagvalues(ids_to_check)


def do_pre_delete(project_id, model, pks_to_delete, is_for_project):
    "More model-specific cleanup, if needed; only for Event model at the moment."

    if model.__name__ != "Event":
        return  # we only do more cleanup for Event

    from projects.models import Project
    from events.models import Event
    from events.retention import cleanup_events_on_storage

    cleanup_events_on_storage(
        Event.objects.filter(pk__in=pks_to_delete).exclude(storage_backend=None)
        .values_list("id", "storage_backend")
    )

    if is_for_project:
        # no need to update the stored_event_count for the project, because the project is being deleted
        return

    # Update project stored_event_count to reflect the deletion of the events. note: alternatively, we could do this
    # on issue-delete (issue.stored_event_count is known too); potato, potato though.
    # note: don't bother to do the same thing for Issue.stored_event_count, since we're in the process of deleting Issue
    Project.objects.filter(id=project_id).update(stored_event_count=F('stored_event_count') - len(pks_to_delete))


def delete_deps_with_budget(project_id, referring_model, fk_name, referred_ids, budget, dep_graph, is_for_project):
    r"""
    Deletes all objects of type referring_model that refer to any of the referred_ids via fk_name.
    Returns the number of deleted objects.
    And does this recursively (i.e. if there are further dependencies, it will delete those as well).

        Caller              This Func
          |                     |
          V                     V
     <unspecified>        referring_model
             ^                  /
             \-------fk_name----

        referred_ids        relevant_ids (deduced using a query)
    """
    num_deleted = 0

    # Fetch ids of referring objects and their referred ids. Note that an index of fk_name can be assumed to exist,
    # because fk_name is a ForeignKey field, and Django automatically creates an index for ForeignKey fields unless
    # instructed otherwise: https://github.com/django/django/blob/7feafd79a481/django/db/models/fields/related.py#L1025
    relevant_ids = list(
       referring_model.objects.filter(**{f"{fk_name}__in": referred_ids}).order_by(f"{fk_name}_id", 'pk').values(
           *(('pk',) + fields_for_prune_orphans(referring_model))
        )[:budget]
    )

    if not relevant_ids:
        # we didn't find any referring objects. optimization: skip any recursion and referring_model.delete()
        return 0

    # The recursing bit:
    for_recursion = dep_graph.get(f"{referring_model._meta.app_label}.{referring_model.__name__}", [])

    for model_for_recursion, fk_name_for_recursion in for_recursion:
        num_deleted += delete_deps_with_budget(
            project_id,
            model_for_recursion,
            fk_name_for_recursion,
            [d["pk"] for d in relevant_ids],
            budget - num_deleted,
            dep_graph,
            is_for_project,
        )

        if num_deleted >= budget:
            return num_deleted

    # If this point is reached: we have deleted all referring objects that we could delete, and we still have budget
    # left. We can now delete the referring objects themselves (limited by budget).
    relevant_ids_after_rec = relevant_ids[:budget - num_deleted]

    do_pre_delete(project_id, referring_model, [d['pk'] for d in relevant_ids_after_rec], is_for_project)

    my_num_deleted, del_d = referring_model.objects.filter(pk__in=[d['pk'] for d in relevant_ids_after_rec]).delete()
    num_deleted += my_num_deleted
    assert_(set(del_d.keys()) == {referring_model._meta.label})  # assert no-cascading (we do that ourselves)

    if is_for_project:
        # short-circuit: project-deletion implies "no orphans" because the project kill everything with it.
        return num_deleted

    # Note that prune_orphans doesn't respect the budget. Reason: it's not easy to do, b/c the order is reversed (we
    # would need to predict somehow at the previous step how much budget to leave unused) and we don't care _that much_
    # about a precise budget "at the edges of our algo", as long as we don't have a "single huge blocking thing".
    prune_orphans(referring_model, relevant_ids_after_rec)

    return num_deleted


def assert_(condition, message=None):
    """Replacement for the `assert` statement as a function. Avoids the (possibly optimized-out) assert statement."""
    if not condition:
        if message is None:
            raise AssertionError()
        raise AssertionError(message)
