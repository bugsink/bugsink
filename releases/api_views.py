from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_pagination import AscDescCursorPagination
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
    """
    LIST requires: ?project=<id>
    Ordered by sort_epoch.
    CREATE allowed. DELETE potential TODO.
    """
    queryset = Release.objects.all()
    serializer_class = ReleaseListSerializer
    http_method_names = ["get", "post", "head", "options"]
    pagination_class = ReleasePagination

    @extend_schema(
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
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        query_params = self.request.query_params
        project_id = query_params.get("project")
        if not project_id:
            raise ValidationError({"project": ["This field is required."]})

        return queryset.filter(project=project_id)

    def get_serializer_class(self):
        if self.action == "create":
            return ReleaseCreateSerializer
        if self.action == "retrieve":
            return ReleaseDetailSerializer
        return ReleaseListSerializer
