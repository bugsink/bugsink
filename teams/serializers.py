from rest_framework import serializers
from bugsink.api_fields import make_enum_field
from .models import Team, TeamVisibility


TeamVisibilityField = make_enum_field(TeamVisibility)


class TeamListSerializer(serializers.ModelSerializer):
    visibility = TeamVisibilityField()

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]


class TeamDetailSerializer(serializers.ModelSerializer):
    visibility = TeamVisibilityField()

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]


class TeamCreateUpdateSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    visibility = TeamVisibilityField(required=False)

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]
