from rest_framework import serializers
from bugsink.api_fields import make_enum_field
from bugsink.api_serializers import UTCModelSerializer
from .models import Team, TeamVisibility


TeamVisibilityField = make_enum_field(TeamVisibility)


class TeamListSerializer(UTCModelSerializer):
    visibility = TeamVisibilityField()

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]


class TeamDetailSerializer(UTCModelSerializer):
    visibility = TeamVisibilityField()

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]


class TeamCreateUpdateSerializer(UTCModelSerializer):
    id = serializers.UUIDField(read_only=True)
    visibility = TeamVisibilityField(required=False)

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]
