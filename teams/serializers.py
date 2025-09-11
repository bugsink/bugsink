from rest_framework import serializers
from bugsink.api_fields import EnumLowercaseChoiceField
from .models import Team, TeamVisibility


class TeamListSerializer(serializers.ModelSerializer):
    visibility = EnumLowercaseChoiceField(TeamVisibility)

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]


class TeamDetailSerializer(serializers.ModelSerializer):
    visibility = EnumLowercaseChoiceField(TeamVisibility)

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]


class TeamCreateUpdateSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    visibility = EnumLowercaseChoiceField(TeamVisibility, required=False)

    class Meta:
        model = Team
        fields = ["id", "name", "visibility"]
