from rest_framework import status, viewsets
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiTypes

from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_capabilities import lookup, token_guard
from bugsink.api_mixins import AtomicRequestMixin

from .models import Release
from .serializers import ReleaseListSerializer, ReleaseDetailSerializer, ReleaseCreateSerializer


class ReleasePagination(AscDescCursorPagination):
    # Cursor pagination requires an indexed, mostly-stable ordering field. We use `digest_order`: We require
    # ?project=<id> and have a composite (project_id, date_released) index, so ORDER BY date_released after filtering by
    # project is fast and cursor-stable. (also note that date_released generally comes in in-order).
    base_ordering = ("date_released",)
    page_size = 250
    default_direction = "desc"


class ReleaseViewSet(AtomicRequestMixin, viewsets.ModelViewSet):
    queryset = Release.objects.all()
    serializer_class = ReleaseListSerializer
    http_method_names = ["get", "post", "head", "options"]
    pagination_class = ReleasePagination

    @token_guard("releases:read", guarding_project=lookup(query="project"))
    @extend_schema(
        summary="List releases",
        description=(
            "List releases for a project. "
            "Pass the integer project ID in the required `project` query parameter."
        ),
        parameters=[
            OpenApiParameter(
                name="project",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Filter releases by project id (required).",
            ),
        ]
    )
    def list(self, request, project, *args, **kwargs):
        self.project = project
        return super().list(request, *args, **kwargs)

    @token_guard("releases:create", guarding_project=lookup(serializer="project"))
    @extend_schema(
        summary="Create a release",
        description=(
            "Create a release for a project. "
            "`project` is the integer project ID. `version` is the release version string."
        ),
        request=ReleaseCreateSerializer,
        responses=ReleaseDetailSerializer,
        examples=[
            OpenApiExample(
                "Create release",
                value={"project": 1, "version": "my-package@1.2.3"},
                request_only=True,
            ),
        ],
    )
    def create(self, request, serializer, project, *args, **kwargs):
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @token_guard("releases:read", guarding_release=lookup(url="pk"))
    @extend_schema(
        summary="Retrieve a release",
        description="Retrieve a release by release UUID.",
        responses=ReleaseDetailSerializer,
    )
    def retrieve(self, request, release, *args, **kwargs):
        return Response(self.get_serializer(release).data)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        return queryset.filter(project=self.project)

    def get_serializer_class(self):
        if self.action == "create":
            return ReleaseCreateSerializer
        if self.action == "retrieve":
            return ReleaseDetailSerializer
        return ReleaseListSerializer
