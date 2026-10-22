from datetime import timedelta, timezone as dt_timezone

from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response

from .usage import EVENT_COUNTS_PER_HOUR_MAX_AGE, hour_bucket


class EventCountRangeSerializer(serializers.Serializer):
    start = serializers.DateTimeField(
        required=False, default_timezone=dt_timezone.utc,
        help_text="Inclusive UTC hour boundary. Defaults to 24 hours before end.")
    end = serializers.DateTimeField(
        required=False, default_timezone=dt_timezone.utc,
        help_text="Exclusive UTC hour boundary. Defaults to the end of the current hour.")

    def validate(self, attrs):
        current_hour = hour_bucket(timezone.now())
        end = attrs.get("end", current_hour + timedelta(hours=1))
        start = attrs.get("start", end - timedelta(hours=24))
        for name, value in [("start", start), ("end", end)]:
            if value != hour_bucket(value):
                raise serializers.ValidationError({name: ["Must be on a UTC hour boundary."]})
        if start >= end:
            raise serializers.ValidationError({"end": ["Must be after start."]})
        if end - start > EVENT_COUNTS_PER_HOUR_MAX_AGE:
            raise serializers.ValidationError({"start": ["The range cannot exceed 90 days."]})
        if start < current_hour - EVENT_COUNTS_PER_HOUR_MAX_AGE:
            raise serializers.ValidationError({"start": ["Hourly counts are retained for 90 days."]})
        if end > current_hour + timedelta(hours=1):
            raise serializers.ValidationError({"end": ["Cannot be later than the end of the current hour."]})
        return {"start": start, "end": end}


class EventCountBucketSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField(default_timezone=dt_timezone.utc)
    count = serializers.IntegerField()


class EventCountsSerializer(serializers.Serializer):
    start = serializers.DateTimeField(default_timezone=dt_timezone.utc)
    end = serializers.DateTimeField(default_timezone=dt_timezone.utc)
    interval_seconds = serializers.IntegerField()
    buckets = EventCountBucketSerializer(many=True)


def event_counts_response(queryset, query_params):
    serializer = EventCountRangeSerializer(data=query_params)
    serializer.is_valid(raise_exception=True)
    start = serializer.validated_data["start"]
    end = serializer.validated_data["end"]
    counts = dict(queryset.filter(bucket__gte=start, bucket__lt=end).values_list("bucket", "count"))
    buckets = []
    timestamp = start
    while timestamp < end:
        buckets.append({"timestamp": timestamp, "count": counts.get(timestamp, 0)})
        timestamp += timedelta(hours=1)
    return Response(EventCountsSerializer({
        "start": start,
        "end": end,
        "interval_seconds": 3600,
        "buckets": buckets,
    }).data)
