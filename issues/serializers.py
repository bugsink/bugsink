import datetime

from django.utils import timezone
from rest_framework import serializers

from bugsink.api_serializers import UTCModelSerializer
from bugsink.period_utils import DATEUTIL_KWARGS_MAP

from .models import Issue, TurningPoint, TurningPointKind, issue_lookup_kwargs


class IssueSerializer(UTCModelSerializer):
    # grouping_keys = serializers.SerializerMethodField()  # read-only list of strings
    friendly_id = serializers.CharField(read_only=True)

    class Meta:
        model = Issue

        # TODO better wording:
        # This is the first attempt at getting the list of fields right. My belief is: this is a nice minimal list.
        # it _does_ contain `data`, which is typically quite "fat", but I'd say that's the most useful field to have.
        # and when you're actually in the business of looking at a specific event, you want to see the data.
        fields = [
            "id",
            "friendly_id",
            "project",
            "digest_order",
            "last_seen",
            "first_seen",
            "digested_event_count",
            "stored_event_count",
            "calculated_type",
            "calculated_value",
            "transaction",
            # "last_frame_filename",
            # "last_frame_module",
            # "last_frame_function",
            "is_resolved",
            "is_resolved_unconditionally",
            "is_resolved_by_next_release",
            # "fixed_at",  too "raw"? i.e. too implementation-tied?
            # "events_at",  too "raw"? i.e. too implementation-tied?
            "is_muted",
            # "unmute_on_volume_based_conditions",  too "raw"? i.e. too implementation-tied?
            # "grouping_keys",  TODO (likely) once we have the "expand" idea implemented
        ]

    # def get_grouping_keys(self, obj):
    #     # TODO: prefetch grouping_key in IssueViewSet
    #     return list(obj.grouping_set.values_list("grouping_key", flat=True))


class IssueMuteForSerializer(serializers.Serializer):
    period_name = serializers.ChoiceField(choices=tuple(DATEUTIL_KWARGS_MAP.keys()))
    nr_of_periods = serializers.IntegerField(min_value=1)


class IssueMuteUntilSerializer(IssueMuteForSerializer):
    gte_threshold = serializers.IntegerField(min_value=1)


class IssueField(serializers.CharField):
    def to_internal_value(self, value):
        value = super().to_internal_value(value)
        try:
            return Issue.objects.filter(is_deleted=False).select_related("project").get(**issue_lookup_kwargs(value))
        except Issue.DoesNotExist:
            raise serializers.ValidationError("Issue not found.")

    def to_representation(self, issue):
        return str(issue.id)  # JSON wants strings, not UUIDs.


class IssueCommentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    issue = IssueField()
    project = serializers.IntegerField(source="project_id", read_only=True)
    timestamp = serializers.DateTimeField(read_only=True, default_timezone=datetime.timezone.utc)
    comment = serializers.CharField(allow_blank=False, trim_whitespace=True)
    user = serializers.IntegerField(source="user_id", read_only=True, allow_null=True)

    def create(self, validated_data):
        issue = validated_data["issue"]
        return TurningPoint.objects.create(
            project=issue.project,
            issue=issue,
            kind=TurningPointKind.MANUAL_ANNOTATION,
            user=None,  # Bearer-token API auth currently represents a global token, not a user.
            comment=validated_data["comment"],
            timestamp=timezone.now(),
        )
