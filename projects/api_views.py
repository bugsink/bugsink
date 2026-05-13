from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_mixins import ExpandViewSetMixin, AtomicRequestMixin

from .models import Project
from .serializers import (
    ProjectListSerializer,
    ProjectDetailSerializer,
    ProjectCreateUpdateSerializer,
)


class ProjectPagination(AscDescCursorPagination):
    # Cursor pagination requires an indexed, mostly-stable ordering field. We use `name`, which is indexed; for Teams,
    # updates are rare and the table is small, so "requirement met in practice though not in theory".
    base_ordering = ("name",)
    page_size = 250
    default_direction = "asc"


class ProjectViewSet(AtomicRequestMixin, ExpandViewSetMixin, viewsets.ModelViewSet):
    queryset = Project.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = ProjectPagination

    @extend_schema(
        summary="List projects",
        description="List projects ordered by name.",
        parameters=[
            OpenApiParameter(
                name="team",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional filter by team UUID.",
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Create a project",
        description="Create a project. `team` is the team UUID. `visibility` and alert settings are optional.",
        request=ProjectCreateUpdateSerializer,
        responses=ProjectCreateUpdateSerializer,
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="Retrieve a project",
        description="Retrieve a project by integer project ID. Use `expand=team` to include the team object.",
        parameters=[
            OpenApiParameter(
                name="expand",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["team"],
                description="Optional related object expansion.",
            ),
        ],
        responses=ProjectDetailSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Update a project",
        description="Partially update a project by integer project ID.",
        request=ProjectCreateUpdateSerializer,
        responses=ProjectCreateUpdateSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        if self.action != "list":
            return queryset
        query_params = self.request.query_params

        # Hide soft-deleted in lists
        qs = queryset.filter(is_deleted=False)

        # Optional team filter (no hard requirement; avoids guessing UI rules)
        team_id = query_params.get("team")
        if team_id:
            qs = qs.filter(team=team_id)

        return qs

    def get_object(self):
        # Pure PK lookup (bypass filter_queryset)
        # NOTE: alternatively, we just complain hard when a filter is applied to a detail view.
        queryset = self.get_queryset()
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        obj = get_object_or_404(queryset, **{self.lookup_field: self.kwargs[lookup_url_kwarg]})
        self.check_object_permissions(self.request, obj)
        return obj

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return ProjectCreateUpdateSerializer
        if self.action == "retrieve":
            return ProjectDetailSerializer
        return ProjectListSerializer
