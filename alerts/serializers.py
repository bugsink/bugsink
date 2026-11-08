from rest_framework import serializers

from bugsink.api_serializers import UTCModelSerializer
from projects.models import Project

from .models import MessagingServiceConfig


class MessagingServiceConfigSerializer(UTCModelSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.filter(is_deleted=False))
    # write-only: the config holds secrets (webhook URLs, bot tokens) and is never returned. The per-kind config form
    # validates it in the view, after authorization, because that validation resolves the webhook's hostname.
    config = serializers.DictField(child=serializers.CharField(allow_blank=True, allow_null=True), write_only=True)

    class Meta:
        model = MessagingServiceConfig
        fields = ["id", "project", "display_name", "kind", "config"]
        extra_kwargs = {"kind": {"required": True}}


class MessagingServiceConfigUpdateSerializer(MessagingServiceConfigSerializer):
    class Meta(MessagingServiceConfigSerializer.Meta):
        read_only_fields = ["project", "kind"]

    project = serializers.PrimaryKeyRelatedField(read_only=True)
