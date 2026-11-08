import json

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_capabilities import lookup, token_guard
from bugsink.transaction import durable_atomic, immediate_atomic

from .api_schema import MessagingServiceSchema, messaging_service_create_schema
from .models import MessagingServiceConfig, get_alert_service_backend_class
from .serializers import MessagingServiceConfigSerializer, MessagingServiceConfigUpdateSerializer


class MessagingServicePagination(AscDescCursorPagination):
    base_ordering = ("id",)
    page_size = 250
    default_direction = "asc"


class MessagingServiceViewSet(
        mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    schema = MessagingServiceSchema()
    queryset = MessagingServiceConfig.objects.all()
    serializer_class = MessagingServiceConfigSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
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
            "Add a messaging service to a project. `kind` selects the backend and its required configuration fields. "
            "Configuration is validated using the same rules as the UI and is never returned."
        ),
        request={"application/json": messaging_service_create_schema()},
        responses={201: MessagingServiceConfigSerializer},
    )
    def create(self, request, serializer, project, *args, **kwargs):
        config = validate_config(serializer.validated_data["kind"], serializer.validated_data["config"])
        with immediate_atomic():
            serializer.save(config=config)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @token_guard("projects:manage", guarding_messaging_service=lookup(url="pk"))
    @extend_schema(
        summary="Update a messaging service",
        description=(
            "Change the display name or replace the complete configuration. "
            "The project and backend kind cannot be changed. `config` is never returned."
        ),
    )
    def partial_update(self, request, messaging_service, *args, **kwargs):
        serializer = self.get_serializer(messaging_service, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "config" in serializer.validated_data:
            serializer.validated_data["config"] = validate_config(
                messaging_service.kind, serializer.validated_data["config"])

        with immediate_atomic():
            serializer.save()
        return Response(serializer.data)

    @immediate_atomic()
    @token_guard("projects:manage", guarding_messaging_service=lookup(url="pk"))
    @extend_schema(summary="Delete a messaging service", responses={204: None})
    def destroy(self, request, messaging_service, *args, **kwargs):
        messaging_service.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @token_guard("projects:manage", guarding_messaging_service=lookup(url="pk"))
    @extend_schema(summary="Send a test message", request=None, responses={202: None})
    @action(detail=True, methods=["post"], url_path="test-send")
    def test_send(self, request, messaging_service, *args, **kwargs):
        messaging_service.get_backend().send_test_message()
        return Response(status=status.HTTP_202_ACCEPTED)

    def get_serializer_class(self):
        if self.action == "partial_update":
            return MessagingServiceConfigUpdateSerializer
        return MessagingServiceConfigSerializer

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        return queryset.filter(project=self.project)


def validate_config(kind, config):
    form = get_alert_service_backend_class(kind).get_form_class()(data=config)
    if not form.is_valid():
        raise ValidationError({"config": form.errors})
    return json.dumps(form.get_config())
