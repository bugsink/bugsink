from django.db.models import Q

from snappea.decorators import shared_task

from bugsink.moreiterutils import batched
from bugsink.transaction import immediate_atomic, delay_on_commit
from tags.models import TagValue, TagKey, EventTag, IssueTag, _or_join, prune_tagvalues

BATCH_SIZE = 10_000


@shared_task
def vacuum_tagvalues(min_id=0):
    # This task cleans up unused TagValue in batches. A TagValue can be unused if no IssueTag or EventTag references it,
    # this can happen if IssueTag or EventTag entries are deleted. Cleanup is avoided in that case to avoid repeated
    # checks. But it still needs to be done eventually to avoid bloating the database, which is what this task does.

    # Impl. notes:
    #
    # * select id_to_check first, and then check which of those are used in EventTag or IssueTag. This avoids doing
    #   TagValue.exclude(some_usage_pattern) which may be slow / for which reasoning about performance is hard.
    # * batched to allow for incremental cleanup, using a defer-with-min-id pattern to implement the batching.
    #
    # Known limitation:
    # with _many_ TagValues (whether used or not) and when running in EAGER mode, this thing overflows the stack.
    # Basically: because then the "delayed recursion" is not actually delayed, it just runs immediately. Answer: for
    # "big things" (basically: serious setups) set up snappea.

    with immediate_atomic():
        # Select candidate TagValue IDs above min_id
        ids_to_check = list(
            TagValue.objects
            .filter(id__gt=min_id)
            .order_by('id')
            .values_list('id', flat=True)[:BATCH_SIZE]
        )

        if not ids_to_check:
            # Done with TagValues → start TagKey cleanup
            delay_on_commit(vacuum_tagkeys, 0)
            return

        # Determine which ids_to_check are referenced
        used_in_event = set(
            EventTag.objects.filter(value_id__in=ids_to_check).values_list('value_id', flat=True)
        )
        used_in_issue = set(
            IssueTag.objects.filter(value_id__in=ids_to_check).values_list('value_id', flat=True)
        )

        unused = [pk for pk in ids_to_check if pk not in used_in_event and pk not in used_in_issue]

        # Actual deletion
        if unused:
            TagValue.objects.filter(id__in=unused).delete()

    # Defer next batch
    vacuum_tagvalues.delay(ids_to_check[-1])


@shared_task
def vacuum_tagkeys(min_id=0):
    with immediate_atomic():
        # Select candidate TagKey IDs above min_id
        ids_to_check = list(
            TagKey.objects
            .filter(id__gt=min_id)
            .order_by('id')
            .values_list('id', flat=True)[:BATCH_SIZE]
        )

        if not ids_to_check:
            return  # done

        # Determine which ids_to_check are referenced
        used = set(
            TagValue.objects.filter(key_id__in=ids_to_check).values_list('key_id', flat=True)
        )

        unused = [pk for pk in ids_to_check if pk not in used]

        # Actual deletion
        if unused:
            TagKey.objects.filter(id__in=unused).delete()

    # Defer next batch
    vacuum_tagkeys.delay(ids_to_check[-1])


@shared_task
def vacuum_eventless_issuetags(min_id=0):
    # This task removes IssueTag entries that are no longer referenced by any EventTag for an Event on the same Issue.
    #
    # Under normal operation, we evict Events and their EventTags. However, we do not track how many EventTags back
    # an IssueTag, so we have historically chosen not to clean up IssueTags during Event deletion. (see #134)
    #
    # This has the upside of being cheap and preserving all known values for an Issue (e.g. all environments/releases
    # ever seen). But it comes with downsides:
    #
    # * stale IssueTags remain for deleted Events
    # * search-by-tag may return Issues without matching Events
    # * TagValues will not be vacuumed as long as they’re still referenced by an IssueTag
    #
    # This task aims to reconcile that, in a delayed and resumable fashion.

    # Empirically determined: at this size, each batch is approx .3s (local dev, sqlite); Note that we're "nearer to the
    # edge of the object-graph" than for e.g. even-retention, so we can both afford bigger batches (less cascading
    # effects per item) as well as need bigger batches (because there are more expected items in a fanning-out
    # object-graph).
    BATCH_SIZE = 2048

    # Community wisdom (says ChatGPT, w/o source): queries with dozens of OR clauses can slow down significantly. 64 is
    # a safe, batch size that avoids planner overhead and keeps things fast across databases.
    INNER_BATCH_SIZE = 64

    with immediate_atomic():
        issue_tag_infos = list(
            IssueTag.objects
            .filter(id__gt=min_id)
            .order_by('id')
            .values('id', 'issue_id', 'value_id')[:BATCH_SIZE]
        )

        for issue_tag_infos_batch in batched(issue_tag_infos, INNER_BATCH_SIZE):
            matching_eventtags = _or_join([
                Q(issue_id=it['issue_id'], value_id=it['value_id']) for it in issue_tag_infos_batch
            ])

            if matching_eventtags:
                in_use_issue_value_pairs = set(
                    EventTag.objects
                    .filter(matching_eventtags)
                    .values_list('issue_id', 'value_id')
                )
            else:
                in_use_issue_value_pairs = set()

            stale_issuetags = [
                it
                for it in issue_tag_infos_batch
                if (it['issue_id'], it['value_id']) not in in_use_issue_value_pairs
            ]

            if stale_issuetags:
                IssueTag.objects.filter(id__in=[it['id'] for it in stale_issuetags]).delete()

                # inline pruning of TagValue (as opposed to using "vacuum later") following the same reasoning as in
                # prune_orphans.
                prune_tagvalues([it['value_id'] for it in stale_issuetags])

    if not issue_tag_infos:
        # We don't have a continuation for the "done" case. One could argue: kick off vacuum_tagvalues there, but I'd
        # rather rather build the toolbox of cleanup tasks first and see how they might fit together later. Because the
        # downside of triggering the next vacuum command would be that "more things might happen too soon".
        return

    vacuum_eventless_issuetags.delay(issue_tag_infos[-1]['id'])
