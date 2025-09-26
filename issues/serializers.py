from bugsink.api_serializers import UTCModelSerializer

from .models import Issue


class IssueSerializer(UTCModelSerializer):
    # grouping_keys = serializers.SerializerMethodField()  # read-only list of strings

    class Meta:
        model = Issue

        # TODO better wording:
        # This is the first attempt at getting the list of fields right. My belief is: this is a nice minimal list.
        # it _does_ contain `data`, which is typically quite "fat", but I'd say that's the most useful field to have.
        # and when you're actually in the business of looking at a specific event, you want to see the data.
        fields = [
            "id",
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
