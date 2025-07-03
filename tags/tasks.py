from snappea.decorators import shared_task

from bugsink.transaction import immediate_atomic, delay_on_commit
from tags.models import TagValue, TagKey, EventTag, IssueTag

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
