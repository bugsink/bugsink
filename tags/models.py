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
from django.db.models import Q, F

from projects.models import Project
from tags.utils import deduce_tags, is_mostly_unique


class TagKey(models.Model):
    project = models.ForeignKey(Project, blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    key = models.CharField(max_length=32, blank=False, null=False)

    # Tags that are "mostly unique" are not displayed in the issue tag counts, because the distribution of values is
    # too flat to provide useful information. Another way of thinking about this is "this is a tag for searching, but
    # not for counting".
    mostly_unique = models.BooleanField(default=False)

    # I briefly considered being explicit about is_deduced; but it's annoying to store this info on the TagKey, and it's
    # probably redundant if we just come up with a list of "reserved" tags or similar.
    # is_deduced = models.BooleanField(default=False)

    class Meta:
        unique_together = ('project', 'key')
        indexes = [
            # Untested assumption: when searching, we search by TagValue[..]key__key=key, so we need an
            # index-not-prefixed-by-project too
            models.Index(fields=['key']),
        ]


class TagValue(models.Model):
    project = models.ForeignKey(Project, blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    # CASCADE: TBD; one argument might be: decouple deletions from events ingestion, but at least have them internally
    # consistent
    key = models.ForeignKey(TagKey, blank=False, null=False, on_delete=models.CASCADE)
    value = models.CharField(max_length=200, blank=False, null=False, db_index=True)

    class Meta:
        # matches what we do in search
        unique_together = ('project', 'key', 'value')

    def __str__(self):
        return f"{self.key.key}:{self.value}"


class EventTag(models.Model):
    project = models.ForeignKey(Project, blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    # value already implies key in our current setup.
    value = models.ForeignKey(TagValue, blank=False, null=False, on_delete=models.CASCADE)

    event = models.ForeignKey('events.Event', blank=False, null=True, on_delete=models.SET_NULL, related_name='tags')

    class Meta:
        unique_together = ('value', 'event')


# class GroupingTag is not needed (not even for future-proofing); it would only be needed if you'd want to "unmerge"
# manually merged issues while preserving the tags/counts. I think that's in "not worth it" territory.


class IssueTag(models.Model):
    project = models.ForeignKey(Project, blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    # value already implies key in our current setup.
    value = models.ForeignKey(TagValue, blank=False, null=False, on_delete=models.CASCADE)

    issue = models.ForeignKey('issues.Issue', blank=False, null=True, on_delete=models.SET_NULL, related_name='tags')

    # As it stands, there is only a single counter per issue-tagvalue combination. In principle/theory this type of
    # denormalization will break down when you want to show this kind of information filtered by some other dimension,
    # because combining such slicings will lead to a combinatorial explosion. However, the only practical such dimension
    # we'll likely want to filter by is "environment". So once we'll actually offer that it's more likely that we'll
    # just implement a separate counter for that dimension, rather than try to do the generic thing ("snuba" at Sentry).
    # And in that case we can probably add the additional constraint that the number of practically observed
    # environments is some small number like 10 (even just because of UI constraints like dropdowns).
    count = models.PositiveIntegerField(default=0)

    class Meta:
        # searching: by value, then Issue (is this so though? .qs is already on the other!)
        unique_together = ('value', 'issue')
        indexes = [
            models.Index(fields=['issue', 'value']),  # make lookups by issue (for detail pages) faster
            # a point _could_ be made for ['issue', 'value' 'count'] we'll probably order by the latter in the end.
            # but I suspect that in practice the sorting on by count can be done easily for a small number of items
            # (and I suspect that if there are very many items, sorting is not useful, because the sparse information
            # does not lead to much insight... but I might be wrong (a few tags with many values, and a long tail would
            # be the counter-example))
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
        k: v[:200] for k, v in deduce_tags(event_data).items()
    }
    store_tags(event, issue, tags)


def store_tags(event, issue, tags):
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
    #         EventTag.objects.get_or_create(project_id=event.project_id, value=tag_value, event=event)
    #         IssueTag.objects.get_or_create(project_id=event.project_id, value=tag_value, issue=issue)
    #
    #     # the 0-case is implied here too, which avoids some further guards in the code below
    #     return

    # there is some principled point here that there is always a single value of mostly_unique per key, but this point
    # is not formalized in our datbase schema; it "just happens to work correctly" (at least as long as we don't change
    # the list of mostly unique keys, at which point we'll have to do a datamigration).
    TagKey.objects.bulk_create([
        TagKey(project_id=event.project_id, key=key, mostly_unique=is_mostly_unique(key)) for key in tags.keys()
    ], ignore_conflicts=True)

    # Select-back what we just created (or was already there); this is needed because "Enabling the ignore_conflicts or
    # update_conflicts parameter disable setting the primary key on each model instance (if the database normally
    # support it)." in Django 4.2; in Django 5.0 and up this is no longer so for `update_conflicts`, so we could use
    # that instead and save a query.
    tag_key_objects = TagKey.objects.filter(project_id=event.project_id, key__in=tags.keys())

    TagValue.objects.bulk_create([
        TagValue(project_id=event.project_id, key=key_obj, value=tags[key_obj.key]) for key_obj in tag_key_objects
    ], ignore_conflicts=True)

    # Select-back what we just created (or was already there); see above; the resulting SQL is a bit more complex than
    # the previous one though, which raises the question whether this is performant.
    tag_value_objects = TagValue.objects.filter(_or_join([
        Q(project_id=event.project_id, key=key_obj, value=tags[key_obj.key]) for key_obj in tag_key_objects]))

    EventTag.objects.bulk_create([
        EventTag(project_id=event.project_id, value=tag_value, event=event) for tag_value in tag_value_objects
    ], ignore_conflicts=True)

    IssueTag.objects.bulk_create([
        IssueTag(project_id=event.project_id, value=tag_value, issue=issue) for tag_value in tag_value_objects
    ], ignore_conflicts=True)

    IssueTag.objects.filter(project_id=event.project_id, value__in=tag_value_objects, issue=issue).update(
        count=F('count') + 1
    )
