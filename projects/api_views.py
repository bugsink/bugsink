from django.shortcuts import get_object_or_404
from rest_framework import viewsets

from .models import Project
from .serializers import (
    ProjectListSerializer,
    ProjectDetailSerializer,
    ProjectCreateUpdateSerializer,
)


class ProjectViewSet(viewsets.ModelViewSet):
    """
    /api/canonical/0/projects/
    GET /projects/           → list ordered by name ASC, hides soft-deleted, optional ?team=<uuid> filter
    GET /projects/{pk}/      → detail (pure PK)
    POST /projects/          → create {team, name, visibility?}
    PATCH /projects/{pk}/    → minimal updates
    DELETE                   → 405
    """
    queryset = Project.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]

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

        # Explicit ordering aligned with UI
        return qs.order_by("name")

    def get_object(self):
        # Pure PK lookup (bypass filter_queryset)
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
