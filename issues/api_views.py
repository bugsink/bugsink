from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_mixins import AtomicRequestMixin
from bugsink.utils import assert_

from .models import Issue, IssueStateManager, TurningPoint, apply_issue_action, issue_lookup_kwargs
from .serializers import (
    IssueCommentSerializer,
    IssueMuteForSerializer,
    IssueMuteUntilSerializer,
    IssueSerializer,
)


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
    RETRIEVE accepts either the issue UUID or friendly ID (soft-deletes implied)
    """
    queryset = Issue.objects.filter(is_deleted=False).select_related("project")  # hide soft-deleted; router basename
    serializer_class = IssueSerializer
    pagination_class = IssuesCursorPagination
    http_method_names = ["get", "post", "delete", "head", "options"]

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

        obj = get_object_or_404(queryset, **issue_lookup_kwargs(self.kwargs[lookup_url_kwarg]))
        self.check_object_permissions(self.request, obj)
        return obj

    def _action_response(self, issue):
        issue.save()
        return Response(self.get_serializer(issue).data)

    def _assert_unresolved(self, issue):
        if issue.is_resolved:
            raise ValidationError({"detail": "Issue is already resolved."})

    def _assert_unmuted(self, issue):
        if issue.is_muted:
            raise ValidationError({"detail": "Issue is already muted."})

    def _apply_issue_action(self, issue, action):
        # Bearer-token API auth currently represents a global token, not a user.
        apply_issue_action(IssueStateManager, issue, action, user=None)
        return self._action_response(issue)

    @extend_schema(
        summary="Resolve an issue",
        description="Mark this issue as resolved. The issue must not already be resolved. No request body is expected.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        issue = self.get_object()
        self._assert_unresolved(issue)
        return self._apply_issue_action(issue, "resolve")

    @extend_schema(
        summary="Resolve an issue in the next release",
        description=(
            "Mark this issue as resolved by the next release. "
            "The issue must not already be resolved. No request body is expected."
        ),
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"], url_path="resolve-next")
    def resolve_next(self, request, pk=None):
        issue = self.get_object()
        self._assert_unresolved(issue)
        return self._apply_issue_action(issue, "resolved_next")

    @extend_schema(
        summary="Resolve an issue in the latest release",
        description=(
            "Mark this issue as resolved in the latest release. "
            "The project must have releases, and the issue must not have occurred in the latest release. "
            "No request body is expected."
        ),
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"], url_path="resolve-latest")
    def resolve_latest(self, request, pk=None):
        issue = self.get_object()
        self._assert_unresolved(issue)
        if not issue.project.has_releases:
            raise ValidationError({"detail": "Project has no releases."})

        latest_release = issue.project.get_latest_release()
        if latest_release.version + "\n" in issue.events_at:
            raise ValidationError({"detail": "Issue has already occurred in the latest release."})

        return self._apply_issue_action(issue, "resolved_release:" + latest_release.version)

    @extend_schema(
        summary="Mute an issue",
        description="Mute this issue. The issue must be unresolved and not already muted. No request body is expected.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"])
    def mute(self, request, pk=None):
        issue = self.get_object()
        self._assert_unresolved(issue)
        self._assert_unmuted(issue)
        return self._apply_issue_action(issue, "mute")

    @extend_schema(
        summary="Mute an issue for a period",
        description="Mute this issue for a relative period. The issue must be unresolved and not already muted.",
        request=IssueMuteForSerializer,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"], url_path="mute-for")
    def mute_for(self, request, pk=None):
        serializer = IssueMuteForSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        period_name = serializer.validated_data["period_name"]
        nr_of_periods = serializer.validated_data["nr_of_periods"]

        issue = self.get_object()
        self._assert_unresolved(issue)
        self._assert_unmuted(issue)
        return self._apply_issue_action(issue, f"mute_for:{period_name},{nr_of_periods},")

    @extend_schema(
        summary="Mute an issue until a threshold is reached",
        description="Mute this issue until a relative period has at least the given number of events.",
        request=IssueMuteUntilSerializer,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"], url_path="mute-until")
    def mute_until(self, request, pk=None):
        serializer = IssueMuteUntilSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        period_name = serializer.validated_data["period_name"]
        nr_of_periods = serializer.validated_data["nr_of_periods"]
        gte_threshold = serializer.validated_data["gte_threshold"]

        issue = self.get_object()
        self._assert_unresolved(issue)
        self._assert_unmuted(issue)
        return self._apply_issue_action(issue, f"mute_until:{period_name},{nr_of_periods},{gte_threshold}")

    @extend_schema(
        summary="Unmute an issue",
        description="Unmute this issue. The issue must be unresolved and muted. No request body is expected.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"])
    def unmute(self, request, pk=None):
        issue = self.get_object()
        self._assert_unresolved(issue)
        if not issue.is_muted:
            raise ValidationError({"detail": "Issue is not muted."})

        return self._apply_issue_action(issue, "unmute")

    def destroy(self, request, *args, **kwargs):
        issue = self.get_object()
        issue.delete_deferred()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # NOTE: No 'unresolve' action: reopen is intentionally not exposed in the UI either. See apply_issue_action.


class IssueCommentViewSet(AtomicRequestMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = TurningPoint.objects.none()  # router basename only
    serializer_class = IssueCommentSerializer
    http_method_names = ["post", "head", "options"]
