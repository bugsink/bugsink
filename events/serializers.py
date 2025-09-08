from rest_framework import serializers

from .models import Event


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event

        # TODO better wording:
        # This is the first attempt at getting the list of fields right. My belief is: this is a nice minimal list.
        # it _does_ contain `data`, which is typically quite "fat", but I'd say that's the most useful field to have.
        # and when you're actually in the business of looking at a specific event, you want to see the data.
        fields = [
            "id",
            "ingested_at",
            "digested_at",
            "issue",
            "grouping",
            "event_id",
            "project",
            "data",  # TODO fetch from disk if so-configured
            "timestamp",
            "digest_order",
        ]
