import json

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_capabilities import lookup, token_guard
from bugsink.transaction import durable_atomic, immediate_atomic

from .models import MessagingServiceConfig, get_alert_service_backend_class
from .serializers import MessagingServiceConfigSerializer


class MessagingServicePagination(AscDescCursorPagination):
    base_ordering = ("id",)
    page_size = 250
    default_direction = "asc"


class MessagingServiceViewSet(
        mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = MessagingServiceConfig.objects.all()
    serializer_class = MessagingServiceConfigSerializer
    http_method_names = ["get", "post", "head", "options"]
    pagination_class = MessagingServicePagination

    @durable_atomic()
    @token_guard("projects:manage", guarding_project=lookup(query="project"))
    @extend_schema(
        summary="List messaging services",
        description=(
            "List the messaging services of a project. "
            "Pass the integer project ID in the required `project` query parameter. `config` is never returned."
        ),
        parameters=[
            OpenApiParameter(
                name="project",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Filter messaging services by project id (required).",
            ),
        ]
    )
    def list(self, request, project, *args, **kwargs):
        self.project = project
        return super().list(request, *args, **kwargs)

    @token_guard("projects:manage", guarding_project=lookup(serializer="project"))
    @extend_schema(
        summary="Add a messaging service",
        description=(
            "Add a messaging service to a project. `project` is the integer project ID. `config` holds the "
            "settings for `kind`, e.g. `{\"webhook_url\": \"...\"}` for Discord; it is write-only."
        ),
    )
    def create(self, request, serializer, project, *args, **kwargs):
        kind = serializer.validated_data["kind"]
        config_form = get_alert_service_backend_class(kind).get_form_class()(data=serializer.validated_data["config"])
        if not config_form.is_valid():
            raise ValidationError({"config": config_form.errors})

        with immediate_atomic():
            serializer.save(config=json.dumps(config_form.get_config()))
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        return queryset.filter(project=self.project)
