import datetime
from django.utils import timezone
from rest_framework import serializers
from bugsink.api_serializers import UTCModelSerializer

from projects.models import Project
from rest_framework.exceptions import ValidationError

from .models import Release, create_release_if_needed


class ReleaseListSerializer(UTCModelSerializer):
    class Meta:
        model = Release
        fields = ["id", "project", "version", "date_released"]


class ReleaseDetailSerializer(UTCModelSerializer):
    class Meta:
        model = Release
        fields = ["id", "project", "version", "date_released", "semver", "is_semver", "sort_epoch"]
        read_only_fields = ["semver", "is_semver", "sort_epoch"]


class ReleaseCreateSerializer(serializers.Serializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    version = serializers.CharField(allow_blank=True)
    timestamp = serializers.DateTimeField(required=False, default_timezone=datetime.timezone.utc)

    def create(self, validated_data):
        project = validated_data["project"]
        version = validated_data["version"]
        timestamp = validated_data.get("timestamp") or timezone.now()

        release, release_created = create_release_if_needed(project=project, version=version, timestamp=timestamp)
        if not release_created:
            raise ValidationError({"version": ["Release with this version already exists for the project."]})
        return release

    def to_representation(self, instance):
        return ReleaseDetailSerializer(instance).data
