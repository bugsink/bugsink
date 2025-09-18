from django.shortcuts import get_object_or_404
from rest_framework import viewsets

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
    """
    /api/canonical/0/teams/
    GET /teams/           → list ordered by name ASC
    GET /teams/{pk}/      → detail (pure PK)
    POST /teams/          → create {name, visibility?}
    PATCH /teams/{pk}/    → minimal updates
    DELETE                → 405
    """
    queryset = Team.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = TeamPagination

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
