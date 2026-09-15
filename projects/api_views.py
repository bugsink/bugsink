from rest_framework import viewsets
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_capabilities import lookup, token_guard
from bugsink.api_mixins import ExpandViewSetMixin, AtomicRequestMixin

from .models import Project, projects_visible_to_user
from .serializers import (
    ProjectListSerializer,
    ProjectDetailSerializer,
    ProjectCreateSerializer,
    ProjectUpdateSerializer,
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

    @token_guard("projects:read")
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

    @token_guard("projects:manage", guarding_team=lookup(serializer="team"))
    @extend_schema(
        summary="Create a project",
        description="Create a project. `team` is the team UUID. `visibility` and alert settings are optional.",
        request=ProjectCreateSerializer,
        responses=ProjectCreateSerializer,
    )
    def create(self, request, serializer, team, *args, **kwargs):
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=201, headers=headers)

    @token_guard("projects:read", guarding_project=lookup(url="pk"))
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
    def retrieve(self, request, project, *args, **kwargs):
        return Response(self.get_serializer(project).data)

    @token_guard("projects:manage", guarding_project=lookup(url="pk"))
    @extend_schema(
        summary="Update a project",
        description="Partially update a project by integer project ID.",
        request=ProjectUpdateSerializer,
        responses=ProjectUpdateSerializer,
    )
    def partial_update(self, request, project, *args, **kwargs):
        serializer = self.get_serializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def filter_queryset(self, queryset):
        if self.action != "list":
            return queryset
        query_params = self.request.query_params

        # Hide soft-deleted in lists
        qs = queryset.filter(is_deleted=False)
        if self.request.auth.is_user_bound:
            qs = projects_visible_to_user(qs, self.request.auth.user)

        # Optional team filter (no hard requirement; avoids guessing UI rules)
        team_id = query_params.get("team")
        if team_id:
            qs = qs.filter(team=team_id)

        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return ProjectCreateSerializer
        if self.action == "partial_update":
            return ProjectUpdateSerializer
        if self.action == "retrieve":
            return ProjectDetailSerializer
        return ProjectListSerializer
