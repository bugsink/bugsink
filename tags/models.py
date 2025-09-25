"""
Tags provide support for arbitrary key/value pairs (both strings) on Events and Issues, allowing for searching &
counting. Some notes:

* Arbitrary Tags can be set programatically in the SDKs, which we need to support (Sentry API Compatability).
* Some "synthetic" Tags are introduced by Bugsink itself: attributes of an Event are deduced and stored explicitly as a
  Tag. The main reason to do this: stay flexible in terms of DB design and allow for generic code for searching and
  counting (especially in the light of Issues, where a single tag can have many values). _However_, we don't make a
  commitment to any particular implementation, and if the deduce-and-store approach turns out to be a performance
  bottleneck, it may be replaced. Particular notes on what we deduce are in `deduce_tags`.

https://docs.sentry.io/platforms/python/enriching-events/tags/

> Tag keys have a maximum length of 32 characters and can contain only letters (a-zA-Z), numbers (0-9), underscores (_),
> periods (.), colons (:), and dashes (-).
>
> Tag values have a maximum length of 200 characters and they cannot contain the newline (\n) character.
"""


from django.db import models
from django.db.models import F, Q
from django.db import connection

from projects.models import Project
from tags.utils import deduce_tags, is_mostly_unique
from bugsink.moreiterutils import batched

# Notes on .project as it lives on TagValue, IssueTag and EventTag:
# In all cases, project could be derived through other means: for TagValue it's implied by TagKey.project; for IssueTag
# it's implied by TagValue (directly, or transitively through TagKey) as well as Issue; likewise for EventTag (but
# through Event there).
# In our current setup, we also always reach these models through queries through one of the models that have .project
# already. Thus, a good case could be made to drop it from the model; but that more or less ties us to the current
# implementation, and I'm not quite willing to do that yet. Hence .project everywhere.
# Once we cleanup-by-project through a filter on project on the model-to-be deleted directly, we will need and
# additional index on 'project' for these models, i.e. models.Index(fields=['project'])


class TagKey(models.Model):
    project = models.ForeignKey(Project, blank=False, null=False, on_delete=models.DO_NOTHING)
    key = models.CharField(max_length=32, blank=False, null=False)

    # Tags that are "mostly unique" are not displayed in the issue tag counts, because the distribution of values is
    # too flat to provide useful information. Another way of thinking about this is "this is a tag for searching, but
    # not for counting".
    mostly_unique = models.BooleanField(default=False)

    # I briefly considered being explicit about is_deduced; but it's annoying to store this info on the TagKey, and it's
    # probably redundant if we just come up with a list of "reserved" tags or similar.
    # is_deduced = models.BooleanField(default=False)

    class Meta:
        # the obvious constraint, which doubles as a lookup index for store_tags and search.
        unique_together = ('project', 'key')

    def __str__(self):
        return f"{self.key}"


class TagValue(models.Model):
    project = models.ForeignKey(Project, blank=False, null=False, on_delete=models.DO_NOTHING)
    key = models.ForeignKey(TagKey, blank=False, null=False, on_delete=models.DO_NOTHING)
    value = models.CharField(max_length=200, blank=False, null=False, db_index=True)

    class Meta:
        # This is the obvious constraint, which doubles as a lookup index for
        # * store_tags (where we look up by both)
        # * search (where we join on key)
        # Note that project is not part of the index, because it's implied by key.
        unique_together = ('key', 'value')

    def __str__(self):
        return f"{self.key.key}:{self.value}"


class EventTag(models.Model):
    project = models.ForeignKey(Project, blank=False, null=False, on_delete=models.DO_NOTHING)

    # value already implies key in our current setup.
    value = models.ForeignKey(TagValue, blank=False, null=False, on_delete=models.DO_NOTHING)

    # issue is a denormalization that allows for a single-table-index for efficient search/vacuum_eventless_issuetags.
    issue = models.ForeignKey(
        'issues.Issue', blank=False, null=False, on_delete=models.DO_NOTHING, related_name="event_tags")

    # digest_order is a denormalization that allows for a single-table-index for efficient search.
    digest_order = models.PositiveIntegerField(blank=False, null=False)

    # DO_NOTHING: we manually implement CASCADE (i.e. when an event is cleaned up, clean up associated tags) in the
    # eviction process.  Why CASCADE? [1] you'll have to do it "at some point", so you might as well do it right when
    # evicting (async in the 'most resilient setup' anyway, b/c that happens when digesting) [2] the order of magnitude
    # is "tens of deletions per event", so that's no reason to postpone. "Why manually" is explained in events/retention
    event = models.ForeignKey('events.Event', blank=False, null=False, on_delete=models.DO_NOTHING, related_name='tags')

    class Meta:
        # This is the obvious constraint
        unique_together = ('value', 'event')

        indexes = [
            models.Index(fields=['event']),  # for lookups by event (for event-details page, event-deletions)

            # for search, which filters a list of EventTag down to those matching certain values and a given issue.
            # (both orderings of the (value, issue) would work for the current search query; if we ever introduce
            # "search across issues" the below would work for that too (but the reverse wouldn't))
            # also used by vacuum_eventless_issuetags (ORed Q(issue_id, value_id))
            models.Index(fields=['value', 'issue', 'digest_order']),
        ]


# class GroupingTag is not needed (not even for future-proofing); it would only be needed if you'd want to "unmerge"
# manually merged issues while preserving the tags/counts. I think that's in "not worth it" territory.


class IssueTag(models.Model):
    project = models.ForeignKey(Project, blank=False, null=False, on_delete=models.DO_NOTHING)

    # denormalization that allows for a single-table-index for efficient search.
    key = models.ForeignKey(TagKey, blank=False, null=False, on_delete=models.DO_NOTHING)

    # value already implies key in our current setup.
    value = models.ForeignKey(TagValue, blank=False, null=False, on_delete=models.DO_NOTHING)

    issue = models.ForeignKey('issues.Issue', blank=False, null=False, on_delete=models.DO_NOTHING, related_name='tags')

    # 1. As it stands, there is only a single counter per issue-tagvalue combination. In principle/theory this type of
    # denormalization will break down when you want to show this kind of information filtered by some other dimension,
    # because combining such slicings will lead to a combinatorial explosion. However, the only practical such dimension
    # we'll likely want to filter by is "environment". So once we'll actually offer that it's more likely that we'll
    # just implement a separate counter for that dimension, rather than try to do the generic thing ("snuba" at Sentry).
    # And in that case we can probably add the additional constraint that the number of practically observed
    # environments is some small number like 10 (even just because of UI constraints like dropdowns).
    # 2. counts are "seen counts", i.e. when events are deleted, the counts are not updated. This is intentional.
    count = models.PositiveIntegerField(default=0)

    class Meta:
        # This is the obvious constraint, which doubles as a lookup index for:
        # * search (a big OR-match on value).
        # * store_tags (counter update filters on both of these)
        unique_together = ('value', 'issue')

        indexes = [
            # for lookups by issue (for detail pages i.e. _get_issue_tags)
            models.Index(fields=['issue', 'key', 'count']),
        ]


# copy/pasta from _and_join; we could move both to a utils module
def _or_join(q_objects):
    if len(q_objects) == 0:
        # we _could_ just return Q(), but I'd force the calling location to not do this
        raise ValueError("empty list of Q objects")

    result = q_objects[0]
    for q in q_objects[1:]:
        result |= q

    return result


def digest_tags(event_data, event, issue):
    # The max length of 200 is from TFM for user-provided tags. Still, we just apply it on deduced tags as well;
    # It's a reasonably safe guess that this will not terribly confuse people, and avoids triggering errors on-save.
    tags = {
        k: str(v)[:200] for k, v in deduce_tags(event_data).items()
    }

    for key in "user.ip_address", "user":
        if tags.get(key) == "{{auto}}":
            if event.remote_addr is None:
                # removing the tag if we don't have the info seems the most faithful to the semantics, i.e. if we don't
                # have the information it shouldn't appear in tags.
                del tags[key]
            else:
                tags[key] = event.remote_addr

    store_tags(event, issue, tags)


def store_tags(event, issue, tags):
    # observed: a non-batched implementation of store_tags() would crash (e.g. in sqlite: Expression tree is too large
    # (maximum depth 1000));

    # The value of 64 was arrived at by trying all powers of 2 (locally, on sqlite), observing that 256 was the last
    # non-failing one, and then taking a factor 4 safety-margin. Realistically, 64 tags _per event_ "should be enough
    # for anyone".
    for kv_batch in batched(tags.items(), 64):
        _store_tags(event, issue, {k: v for k, v in kv_batch})


def _store_tags(event, issue, tags):
    def _uf(fields):
        # mysql "does not support updating conflicts with specifying unique fields that can trigger the upsert.";
        # But for sqlite and postgres the value _is_ required. So empty for mysql, passed fields for the others.
        if connection.vendor == "mysql":  # includes mariadb
            return []
        return fields

    if not tags:
        return  # short-circuit; which is a performance optimization which also avoids some the need for further guards

    # The below is commented-out because in practice each get_or_create() triggers 4(!) queries (savepoint-related)
    # It's left here for reference, because it provides a readable equivalent to the bulk_create approach.
    # if len(tags) <= 1:
    #     # for low numbers of tags the bulk_create approach is not worth it and we just do the straightforward thing.
    #     # note that get_or_create may implies 1 or 2 queries, so the below is in the order of 4-8 _per tag_; which is
    #     # why this is only worth it for very small numbers of tags (1 in the current setup).
    #
    #     for key, value in tags.items():
    #         tag_key, _ = TagKey.objects.get_or_create(
    #             project_id=event.project_id, key=key, mostly_unique=is_mostly_unique(key))
    #         tag_value, _ = TagValue.objects.get_or_create(project_id=event.project_id, key=tag_key, value=value)
    #         EventTag.objects.get_or_create(project_id=event.project_id, value=tag_value, event=event,
    #             defaults={'issue': issue, 'digest_order': event.digest_order})
    #         IssueTag.objects.get_or_create(
    #            project_id=event.project_id, key_id=tag_value.key_id, value=tag_value, issue=issue)
    #
    #     # the 0-case is implied here too, which avoids some further guards in the code below
    #     return

    # there is some principled point here that there is always a single value of mostly_unique per key, but this point
    # is not formalized in our datbase schema; it "just happens to work correctly" (at least as long as we don't change
    # the list of mostly unique keys, at which point we'll have to do a datamigration).
    tag_key_objects = [
        TagKey(project_id=event.project_id, key=key, mostly_unique=is_mostly_unique(key)) for key in tags.keys()
    ]
    TagKey.objects.bulk_create(
        tag_key_objects, update_conflicts=True, unique_fields=_uf(['project', 'key']), update_fields=['mostly_unique'])

    if connection.vendor == "mysql":
        # In mysql, bulk_create does not actually set pk on the created objects, so we need to re-query.
        # 'project_id': in the selection-queries below the non-necessity of the project_id is mentioned a number of
        # times, but that's precisly _because_ we encode the link to project in TagKay. i.e. here it is needed.
        tag_key_objects = TagKey.objects.filter(project_id=event.project_id, key__in=tags.keys())

    tag_value_objects = [
        TagValue(project_id=event.project_id, key=key_obj, value=tags[key_obj.key]) for key_obj in tag_key_objects
    ]

    # 'project' is not part of the unique constraint, which means it goes into update_fields.
    TagValue.objects.bulk_create(
        tag_value_objects, update_conflicts=True, unique_fields=_uf(['key', 'value']), update_fields=['project'])

    if connection.vendor == "mysql":
        # In mysql, bulk_create does not actually set pk on the created objects, so we need to re-query.
        # Select-back what we just created (or was already there);
        # 'project_id' is not needed here, because it's already implied by key_obj.
        tag_value_objects = TagValue.objects.filter(_or_join([
            Q(key=key_obj, value=tags[key_obj.key]) for key_obj in tag_key_objects]))

    EventTag.objects.bulk_create([
        EventTag(
            project_id=event.project_id,
            value=tag_value,
            event=event,
            issue=issue,
            digest_order=event.digest_order,
        ) for tag_value in tag_value_objects
    ], ignore_conflicts=True)

    IssueTag.objects.bulk_create([
        IssueTag(
            project_id=event.project_id,
            key_id=tag_value.key_id,
            value=tag_value,
            issue=issue,
        ) for tag_value in tag_value_objects
    ], ignore_conflicts=True)

    # Re 'project_id': this is not needed here, because it's already implied by both tag_value_objects and issue.
    IssueTag.objects.filter(value__in=tag_value_objects, issue=issue).update(
        count=F('count') + 1
    )


def prune_tagvalues(ids_to_check):
    # used_in_event check is not needed, because non-existence of IssueTag always implies non-existince of EventTag,
    # since [1] EventTag creation implies IssueTag creation and [2] in the cleanup code EventTag is deleted first.
    used_in_issuetag = set(
        IssueTag.objects.filter(value_id__in=ids_to_check).values_list('value_id', flat=True)
    )
    unused = [pk for pk in ids_to_check if pk not in used_in_issuetag]

    if unused:
        TagValue.objects.filter(id__in=unused).delete()

    # The principled approach would be to clean up TagKeys as well at this point, but in practice there will be orders
    # of magnitude fewer TagKey objects, and they are much less likely to become dangling, so the GC-like algo of "just
    # vacuuming once in a while" is a much better fit for that.
