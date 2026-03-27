from django.db.models import Sum
from rest_framework import serializers

from bugsink.api_serializers import UTCModelSerializer
from bugsink.api_fields import make_enum_field
from bugsink.app_settings import get_settings

from teams.models import Team
from bugsink.api_mixins import ExpandableSerializerMixin

from teams.serializers import TeamDetailSerializer
from .models import Project, ProjectVisibility


ProjectVisibilityField = make_enum_field(ProjectVisibility)


class ProjectListSerializer(UTCModelSerializer):
    visibility = ProjectVisibilityField()
    dsn = serializers.CharField(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "team",
            "name",
            "slug",
            "dsn",
            "digested_event_count",
            "stored_event_count",
            "alert_on_new_issue",
            "alert_on_regression",
            "alert_on_unmute",
            "visibility",
            "retention_max_event_count",
        ]


class ProjectDetailSerializer(ExpandableSerializerMixin, UTCModelSerializer):
    expandable_fields = {"team": TeamDetailSerializer}
    visibility = ProjectVisibilityField()
    dsn = serializers.CharField(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "team",
            "name",
            "slug",
            "dsn",
            "digested_event_count",
            "stored_event_count",
            "alert_on_new_issue",
            "alert_on_regression",
            "alert_on_unmute",
            "visibility",
            "retention_max_event_count",
        ]


class ProjectCreateUpdateSerializer(UTCModelSerializer):
    id = serializers.UUIDField(read_only=True)
    team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all())
    visibility = ProjectVisibilityField(required=False)

    class Meta:
        model = Project

        fields = [
            "id",
            "team",
            "name",
            "visibility",
            "alert_on_new_issue",
            "alert_on_regression",
            "alert_on_unmute",
            "retention_max_event_count",
            # "slug", auto-generated for uniqueness
            # "is_deleted", must go through delete_deferred()
            # "digested_event_count",  system-managed counter
            # "stored_event_count",  system-managed counter
            # "has_releases",  system-managed flag
            # "dsn",  derived from base_url + ids + key
            # "sentry_key",  server-generated, not client-writable
            # "quota_exceeded_until",  system-managed quota state
            # "next_quota_check",  system-managed quota scheduler
        ]

        # extra_kwargs: mark alert/retention fields optional on write (they have defaults)
        extra_kwargs = {
            "alert_on_new_issue": {"required": False},
            "alert_on_regression": {"required": False},
            "alert_on_unmute": {"required": False},
            "retention_max_event_count": {"required": False},
        }

    def validate_retention_max_event_count(self, value):
        # This is a pure copy/pate of the logic in projects/forms.py; once we have more and more such logic we should
        # decide on where it should live.

        if get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT is not None:
            if value > get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT:
                raise serializers.ValidationError(
                    f"The maximum allowed retention per project is "
                    f"{get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT} events."
                )

        if get_settings().MAX_RETENTION_EVENT_COUNT is not None:
            instance = getattr(self, "instance", None)

            qs = Project.objects.all()
            if instance and instance.pk:
                qs = qs.exclude(pk=instance.pk)

            sum_of_others = qs.aggregate(total=Sum("retention_max_event_count"))["total"] or 0

            budget_left = max(get_settings().MAX_RETENTION_EVENT_COUNT - sum_of_others, 0)

            if value > budget_left:
                raise serializers.ValidationError(
                    "The maximum allowed retention for this project is "
                    f"{budget_left} events (based on the installation-wide "
                    f"max of {get_settings().MAX_RETENTION_EVENT_COUNT} events)."
                )

        return value
