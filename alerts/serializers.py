from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from bugsink.api_serializers import UTCModelSerializer
from projects.models import Project

from .models import MessagingServiceConfig, get_alert_service_kind_choices
from .api_schema import config_schema


@extend_schema_field({
    "anyOf": [config_schema(kind) for kind, _ in get_alert_service_kind_choices()],
    "description": "Complete configuration for the destination's backend kind. Never returned in responses.",
})
class MessagingServiceConfigField(serializers.DictField):
    def __init__(self, **kwargs):
        super().__init__(child=serializers.CharField(allow_blank=True, allow_null=True), write_only=True, **kwargs)


class MessagingServiceConfigSerializer(UTCModelSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.filter(is_deleted=False))
    # write-only: the config holds secrets (webhook URLs, bot tokens) and is never returned. The per-kind config form
    # validates it in the view, after authorization, because that validation resolves the webhook's hostname.
    config = MessagingServiceConfigField()

    class Meta:
        model = MessagingServiceConfig
        fields = ["id", "project", "display_name", "kind", "config"]
        extra_kwargs = {"kind": {"required": True}}


class MessagingServiceConfigUpdateSerializer(MessagingServiceConfigSerializer):
    class Meta(MessagingServiceConfigSerializer.Meta):
        read_only_fields = ["project", "kind"]

    project = serializers.PrimaryKeyRelatedField(read_only=True)
