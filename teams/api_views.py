from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_capabilities import lookup, token_guard
from bugsink.api_mixins import AtomicRequestMixin

from .models import Team, teams_visible_to_user, user_can_create_team
from .serializers import (
    TeamListSerializer,
    TeamDetailSerializer,
    TeamCreateUpdateSerializer,
)


class TeamPagination(AscDescCursorPagination):
    # Cursor pagination requires an indexed, mostly-stable ordering field. We use `name`, which is indexed; for Teams,
    # updates are rare and the table is small, so "requirement met in practice though not in theory".
    base_ordering = ("name",)
    page_size = 250
    default_direction = "asc"


class TeamViewSet(AtomicRequestMixin, viewsets.ModelViewSet):
    queryset = Team.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = TeamPagination

    @token_guard("teams:read")
    @extend_schema(
        summary="List teams",
        description="List teams ordered by name.",
        responses=TeamListSerializer,
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @token_guard("teams:manage")
    @extend_schema(
        summary="Create a team",
        description="Create a team. `visibility` is optional and defaults to `discoverable`.",
        request=TeamCreateUpdateSerializer,
        responses=TeamCreateUpdateSerializer,
    )
    def create(self, request, *args, **kwargs):
        if request.auth.is_user_bound and not user_can_create_team(request.auth.user):
            raise PermissionDenied("The user bound to this token is not allowed to create teams.")
        return super().create(request, *args, **kwargs)

    @token_guard("teams:read", guarding_team=lookup(url="pk"))
    @extend_schema(
        summary="Retrieve a team",
        description="Retrieve a team by UUID.",
        responses=TeamDetailSerializer,
    )
    def retrieve(self, request, team, *args, **kwargs):
        return Response(self.get_serializer(team).data)

    @token_guard("teams:manage", guarding_team=lookup(url="pk"))
    @extend_schema(
        summary="Update a team",
        description="Partially update a team by UUID.",
        request=TeamCreateUpdateSerializer,
        responses=TeamCreateUpdateSerializer,
    )
    def partial_update(self, request, team, *args, **kwargs):
        serializer = self.get_serializer(team, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action == "list" and self.request.auth.is_user_bound:
            return teams_visible_to_user(queryset, self.request.auth.user)
        return queryset

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return TeamCreateUpdateSerializer
        if self.action == "retrieve":
            return TeamDetailSerializer
        return TeamListSerializer
