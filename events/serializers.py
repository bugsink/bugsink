from rest_framework import serializers

from .models import Event


class EventListSerializer(serializers.ModelSerializer):
    """Lightweight list view: excludes the (potentially large) `data` field."""

    class Meta:
        model = Event
        fields = [
            "id",
            "ingested_at",
            "digested_at",
            "issue",
            "grouping",
            "event_id",
            "project",
            "timestamp",
            "digest_order",
        ]


class EventDetailSerializer(serializers.ModelSerializer):
    """Detail view: includes full `data` payload."""

    class Meta:
        model = Event
        fields = EventListSerializer.Meta.fields + [
            "data",
        ]
