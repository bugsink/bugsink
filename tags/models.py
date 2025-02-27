"""
Tags provide support for arbitrary key/value pairs (both strings) on Events and Issues, allowing for searching &
counting. Some notes:

* Arbitrary Tags can be set programatically in the SDKs, which we need to support (Sentry API Compatability).
* Some "synthetic" Tags are introduced by Bugsink itself: attributes of an Event are deduced and stored explicitly as a
  Tag. The main reason to do this: stay flexible in terms of DB design and allow for generic code for searching and
  counting. _However_, we don't make a commitment to any particular implementation, and if the deduce-and-store approach
  turns out to be a performance bottleneck, it may be replaced. Particular notes on what we deduce are in `deduce_tags`.

https://docs.sentry.io/platforms/python/enriching-events/tags/

> Tag keys have a maximum length of 32 characters and can contain only letters (a-zA-Z), numbers (0-9), underscores (_),
> periods (.), colons (:), and dashes (-).
>
> Tag values have a maximum length of 200 characters and they cannot contain the newline (\n) character.
"""


from django.db import models

from projects.models import Project
from tags.utils import deduce_tags


class TagKey(models.Model):
    project = models.ForeignKey(Project, blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    key = models.CharField(max_length=32, blank=False, null=False)

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

    class Meta:
        # searching: by value, then Issue (is this so though? .qs is already on the other!)
        unique_together = ('value', 'issue')
        indexes = [
            models.Index(fields=['issue', 'value']),  # make lookups by issue (for detail pages) faster
        ]


def digest_tags(event_data, event, issue):
    tags = deduce_tags(event_data)

    for key, value in tags.items():
        # The max length of 200 is from TFM for user-provided tags. Still, we just apply it on synthetic tags as well;
        # It's a reasonably safe guess that this will not terribly confuse people, and avoids triggering errors on-save.
        value = value[:200]

        # TODO just use bulk_create for each of the types of objects
        # TODO check: event.project won't trigger a query, right? it's already loaded, right?
        tag_key, _ = TagKey.objects.get_or_create(project=event.project, key=key)
        tag_value, _ = TagValue.objects.get_or_create(project=event.project, key=tag_key, value=value)
        EventTag.objects.get_or_create(project=event.project, value=tag_value, event=event)
        IssueTag.objects.get_or_create(project=event.project, value=tag_value, issue=issue)
