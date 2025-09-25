from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.pagination import CursorPagination
from rest_framework.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_mixins import AtomicRequestMixin
from bugsink.utils import assert_

from .models import Issue
from .serializers import IssueSerializer


class IssuesCursorPagination(CursorPagination):
    """
    Cursor paginator for /issues supporting ?sort=… and ?order=asc|desc.

    Sort modes are named after the *primary* column:
      - sort=digest_order → unique per project → no tie-breakers needed
      - sort=last_seen    → timestamp          → tie-breaker on id

    Direction applies to primary *and beyond* (i.e. all fields in the list).
    The view MUST filter by project; ordering is handled here.
    """
    # Cursor pagination requires an indexed, mostly-stable ordering. Stable mode: sort=digest_order (default). We
    # require ?project=<uuid> and have a composite (project_id, digest_order) index, so ORDER BY digest_order after
    # filtering by project is fast and cursor-stable.

    # We also offer a "recent" mode: sort=last_seen. This is not stable, as new events can come in mid-cursor, and
    # reshuffle things causing misses or duplicates. However, this is the desired UX for a "recent activity" view.
    # i.e. the typical usage would in fact just be to get the "first page" of recent activity.
    page_size = 250
    default_direction = "asc"
    default_sort = "digest_order"

    VALID_SORTS = ("digest_order", "last_seen")
    VALID_ORDERS = ("asc", "desc")

    def get_ordering(self, request, queryset, view):
        sort = request.query_params.get("sort", self.default_sort)
        if sort not in self.VALID_SORTS:
            raise ValidationError({"sort": ["Must be 'digest_order' or 'last_seen'."]})

        order = request.query_params.get("order", self.default_direction)
        if order not in self.VALID_ORDERS:
            raise ValidationError({"order": ["Must be 'asc' or 'desc'."]})

        desc = (order == "desc")

        if sort == "digest_order":
            # Unique per project; stable cursor once filtered by project.
            return ["-digest_order" if desc else "digest_order"]

        # sort == "last_seen": timestamp needs a deterministic tie-breaker.
        if desc:
            return ["-last_seen", "-id"]
        return ["last_seen", "id"]


class IssueViewSet(AtomicRequestMixin, viewsets.ReadOnlyModelViewSet):
    """
    LIST requires: ?project=<uuid>
    Optional: ?order=asc|desc        (default: desc)
    LIST ordered by last_seen
    RETRIEVE is a pure PK lookup (soft-deletes implied)
    """
    queryset = Issue.objects.filter(is_deleted=False)  # hide soft-deleted issues; also satisfies router
    serializer_class = IssueSerializer
    pagination_class = IssuesCursorPagination

    def get_queryset(self):
        return self.queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="project",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Filter issues by project id (required).",
            ),
            OpenApiParameter(
                name="sort",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["digest_order", "last_seen"],
                description="Sort mode (default: digest_order).",
            ),
            OpenApiParameter(
                name="order",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["asc", "desc"],
                description="Sort order (default: asc).",
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        project = self.request.query_params.get("project")
        if not project:
            # the below at least until we have a UI for cross-project Issue listing, i.e. #190
            raise ValidationError({"project": ["This field is required."]})

        return queryset.filter(project=project)

    def get_object(self):
        """
        DRF's get_object(), but bypass filter_queryset for detail.
        """
        # NOTE: alternatively, we just complain hard when a filter is applied to a detail view.
        # TODO: copy/paste from events/api_views.py
        queryset = self.get_queryset()

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        assert_(
            lookup_url_kwarg in self.kwargs,
            'Expected view %s to be called with a URL keyword argument named "%s".'
            % (self.__class__.__name__, lookup_url_kwarg)
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj
