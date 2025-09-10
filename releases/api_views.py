from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from projects.models import Project
from .models import Release, ordered_releases
from .serializers import ReleaseListSerializer, ReleaseDetailSerializer, ReleaseCreateSerializer


class ReleaseViewSet(viewsets.ModelViewSet):
    """
    LIST requires: ?project=<id>
    Ordered by sort_epoch.
    CREATE allowed. DELETE potential TODO.
    """
    queryset = Release.objects.all()
    serializer_class = ReleaseListSerializer
    http_method_names = ["get", "post", "head", "options"]

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        query_params = self.request.query_params
        project_id = query_params.get("project")
        if not project_id:
            raise ValidationError({"project": ["This field is required."]})

        # application-ordering (as opposed to in-db); will have performance implications, but we do "correct first, fast
        # later":
        project = Project.objects.get(pk=project_id)
        return ordered_releases(project=project)

    def get_serializer_class(self):
        if self.action == "create":
            return ReleaseCreateSerializer
        if self.action == "retrieve":
            return ReleaseDetailSerializer
        return ReleaseListSerializer
