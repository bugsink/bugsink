from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from drf_spectacular.utils import extend_schema

from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_mixins import AtomicRequestMixin

from .models import Team
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

    @extend_schema(
        summary="List teams",
        description="List teams ordered by name.",
        responses=TeamListSerializer,
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Create a team",
        description="Create a team. `visibility` is optional and defaults to `discoverable`.",
        request=TeamCreateUpdateSerializer,
        responses=TeamCreateUpdateSerializer,
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="Retrieve a team",
        description="Retrieve a team by UUID.",
        responses=TeamDetailSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Update a team",
        description="Partially update a team by UUID.",
        request=TeamCreateUpdateSerializer,
        responses=TeamCreateUpdateSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

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
            return TeamCreateUpdateSerializer
        if self.action == "retrieve":
            return TeamDetailSerializer
        return TeamListSerializer
