from rest_framework import serializers
from bugsink.api_fields import EnumLowercaseChoiceField

from teams.models import Team
from .models import Project, ProjectVisibility


class ProjectListSerializer(serializers.ModelSerializer):
    visibility = EnumLowercaseChoiceField(ProjectVisibility)
    dsn = serializers.CharField(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "team",
            "name",
            "slug",
            "is_deleted",
            "dsn",
            "digested_event_count",
            "stored_event_count",
            "alert_on_new_issue",
            "alert_on_regression",
            "alert_on_unmute",
            "visibility",
            "retention_max_event_count",
        ]


class ProjectDetailSerializer(serializers.ModelSerializer):
    visibility = EnumLowercaseChoiceField(ProjectVisibility)
    dsn = serializers.CharField(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "team",
            "name",
            "slug",
            "is_deleted",
            "dsn",
            "digested_event_count",
            "stored_event_count",
            "alert_on_new_issue",
            "alert_on_regression",
            "alert_on_unmute",
            "visibility",
            "retention_max_event_count",
        ]


class ProjectCreateUpdateSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all())
    visibility = EnumLowercaseChoiceField(ProjectVisibility, required=False)

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
