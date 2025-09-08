from rest_framework import serializers

from .models import Project


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            "id",
            "team",
            "name",
            "slug",
            "is_deleted",
            "sentry_key",  # or just: "dsn"
            # users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, through="ProjectMembership")
            "digested_event_count",
            "stored_event_count",
            "alert_on_new_issue",
            "alert_on_regression",
            "alert_on_unmute",
            "visibility",
            "retention_max_event_count",
        ]
