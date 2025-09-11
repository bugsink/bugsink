from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from .models import Team
from .serializers import (
    TeamListSerializer,
    TeamDetailSerializer,
    TeamCreateUpdateSerializer,
)


class TeamViewSet(viewsets.ModelViewSet):
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

    def filter_queryset(self, queryset):
        if self.action != "list":
            return queryset
        # Explicit ordering aligned with UI
        return queryset.order_by("name")

    def get_object(self):
        # Pure PK lookup (bypass filter_queryset)
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
