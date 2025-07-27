from collections import defaultdict
from urllib.parse import urlparse

from django.core.mail import EmailMultiAlternatives
from django.template.loader import get_template
from django.apps import apps
from django.db.models import ForeignKey, F

from .version import version


def send_rendered_email(subject, base_template_name, recipient_list, context=None):
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

    msg.send()


def deduce_allowed_hosts(base_url):
    url = urlparse(base_url)
    if url.hostname == "localhost" or url.hostname == "127.0.0.1":
        # Allow all hosts when running locally. All hosts, because in local setups there are a few common scenarios of
        # named-hosts-that-should-still-be-ok, like:
        # * docker containers with a name
        # * /etc/hosts defining an explicit name for localhost
        # * accessing Bugsink on your local network by ip (192.etc)
        # In production setups, the expectation is that deduce_allowed_hosts is not used with localhost/127.0.0.1
        return ["*"]

    # in production setups, we want to be explicit about the allowed hosts; however, we _still_ add localhost and
    # 127.0.0.1 explicitly, to allow for local loopback testing (e.g. health-checks from the same machine). I believe
    # this is OK (i.e. not a security risk) because the goal of ALLOWED_HOSTS is to "prevent an attacker from poisoning
    # caches and triggering password reset emails with links to malicious hosts by submitting requests with a fake HTTP
    # Host header." Without claiming have a full overview of possible attacks, I believe that they all hinge on the fact
    # that the "poisonous host" is a host under the control of the attacker. I fail to see how "localhost" is a
    # meaningful target in such an attack (since the attacker would already have control over the machine).
    #
    # sources:
    # https://stackoverflow.com/questions/30579248/
    # https://docs.djangoproject.com/en/5.2/ref/settings/#allowed-hosts
    # https://code.djangoproject.com/ticket/28693 (the main source for the relation between CSRF and ALLOWED_HOSTS)
    #
    # security-officers disagreeing with this above: feel free to reach out (and set ALLOWED_HOSTS explicitly).
    return [url.hostname] + ["localhost", "127.0.0.1"]


# Note: the excessive string-matching in the below is intentional:
# I'd rather have our error-handling code as simple as possible
# instead of relying on all kinds of imports of Exception classes.
def _name(type_):
    try:
        return type_.__module__ + "." + type_.__name__
    except Exception:
        try:
            return type_.__name__
        except Exception:
            return "unknown"


def fingerprint_exc(event, exc_info):
    type_name = _name(exc_info[0])
    # exc = exc_info[1]

    if event["exception"]["values"][-1]["stacktrace"]["frames"][-1]["module"] == "bugsink.wsgi":
        # When and Exception occurs in the WSGI handler, we want to override the fingerprint to exclude the transaction
        # (which is URL-based in the default) because something that occurs at the server-level (e.g. DisallowedHost)
        # would occur for all URLs.
        #
        # Road not taken: overriding event["transaction"] to "wsgi" and event["transaction_info"]["source"] to "custom"
        # would preserve a bit more of the server-side grouping behavior; road-not-taken b/c the (or our?) interface so
        # clearly implies "set fingerprints".
        #
        # Note: arguably, the above might be extended to "anything middleware-related" for the same reasons; we'll do
        # that when we have an actual use-case.
        event['fingerprint'] = ['wsgi', type_name]

    return event


def fingerprint_log_record(event, log_record):
    # (hook for future use)
    return event


def fingerprint_before_send(event, hint):
    if 'exc_info' in hint:
        return fingerprint_exc(event, hint['exc_info'])

    if 'log_record' in hint:
        return fingerprint_log_record(event, hint['log_record'])

    return event


def eat_your_own_dogfood(sentry_dsn, **kwargs):
    """
    Configures your Bugsink installation to send messages to some Bugsink-compatible installation.
    See https://www.bugsink.com/docs/dogfooding/
    """
    import sentry_sdk.serializer
    sentry_sdk.serializer.MAX_DATABAG_DEPTH = float("inf")
    sentry_sdk.serializer.MAX_DATABAG_BREADTH = float("inf")

    if sentry_dsn is None:
        return

    default_kwargs = {
        "dsn": sentry_dsn,
        "traces_sample_rate": 0,
        "send_default_pii": True,

        # see (e.g.) https://github.com/getsentry/sentry-python/issues/377 for why this is necessary; I really really
        # dislike Sentry's silent dropping of local variables; let's see whether "just send everything" makes for
        # messages that are too big. If so, we might monkey-patch sentry_sdk/serializer.py 's 2 variables named
        # MAX_DATABAG_DEPTH and MAX_DATABAG_BREADTH (esp. the latter)
        # still not a complete solution until https://github.com/getsentry/sentry-python/issues/3209 is fixed
        "max_request_body_size": "always",

        # In actual development, the list below is not needed, because in that case Sentry's SDK is able to distinguish
        # based on the os.cwd() v.s. site-packages. For cases where the Production installation instructions are
        # followed, that doesn't fly though, because we "just install everything" (using pip install), and we need to be
        # explicit. The notation below (no trailing dot or slash) is the correct one (despite not being documented) as
        # evidenced by the line `if item == name or name.startswith(item + "."):` in the sentry_sdk source:
        "in_app_include": [
            "alerts",
            "bsmain",
            "bugsink",
            "compat",
            "events",
            "ee",
            "ingest",
            "issues",
            "performance",
            "phonehome",
            "projects",
            "releases",
            "sentry",
            "sentry_sdk_extensions",
            "snappea",
            "tags",
            "teams",
            "theme",
            "users",
        ],
        "release": version,
        "before_send": fingerprint_before_send,
    }

    default_kwargs.update(kwargs)

    sentry_sdk.init(
        **default_kwargs,
    )


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
    assert set(del_d.keys()) == {referring_model._meta.label}  # assert no-cascading (we do that ourselves)

    if is_for_project:
        # short-circuit: project-deletion implies "no orphans" because the project kill everything with it.
        return num_deleted

    # Note that prune_orphans doesn't respect the budget. Reason: it's not easy to do, b/c the order is reversed (we
    # would need to predict somehow at the previous step how much budget to leave unused) and we don't care _that much_
    # about a precise budget "at the edges of our algo", as long as we don't have a "single huge blocking thing".
    prune_orphans(referring_model, relevant_ids_after_rec)

    return num_deleted
