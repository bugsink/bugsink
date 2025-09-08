from rest_framework import serializers

from .models import Release


class ReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Release

        # TODO: distinguish read vs write fields
        fields = [
            "id",
            "project",
            "version",
            "date_released",
            "semver",
            "is_semver",
            "sort_epoch",
        ]
