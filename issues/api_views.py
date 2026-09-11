from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_mixins import AtomicRequestMixin
from bugsink.api_capabilities import lookup, token_guard

from .models import Issue, IssueStateManager, TurningPoint, apply_issue_action
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
      - sort=digest_order         → unique per project → no tie-breakers needed
      - sort=last_seen            → timestamp          → tie-breaker on id
      - sort=digested_event_count → lifetime count     → tie-breakers on last_seen and id

    Direction applies to primary *and beyond* (i.e. all fields in the list).
    The view MUST filter by project; ordering is handled here.
    """
    # Cursor pagination requires an indexed, mostly-stable ordering. Stable mode: sort=digest_order (default). We
    # require ?project=<uuid> and have a composite (project_id, digest_order) index, so ORDER BY digest_order after
    # filtering by project is fast and cursor-stable.

    # We also offer a "recent" mode: sort=last_seen. This is not stable, as new events can come in mid-cursor, and
    # reshuffle things causing misses or duplicates. However, this is the desired UX for a "recent activity" view.
    # i.e. the typical usage would in fact just be to get the "first page" of recent activity.
    # Event-count sorting has the same instability when new events arrive.
    page_size = 250
    default_direction = "asc"
    default_sort = "digest_order"

    VALID_SORTS = ("digest_order", "last_seen", "digested_event_count")
    VALID_ORDERS = ("asc", "desc")

    def get_ordering(self, request, queryset, view):
        sort = request.query_params.get("sort", self.default_sort)
        if sort not in self.VALID_SORTS:
            raise ValidationError({
                "sort": ["Must be 'digest_order', 'last_seen', or 'digested_event_count'."],
            })

        order = request.query_params.get("order", self.default_direction)
        if order not in self.VALID_ORDERS:
            raise ValidationError({"order": ["Must be 'asc' or 'desc'."]})

        desc = (order == "desc")

        if sort == "digest_order":
            # Unique per project; stable cursor once filtered by project.
            return ["-digest_order" if desc else "digest_order"]

        fields = ["last_seen", "id"] if sort == "last_seen" else ["digested_event_count", "last_seen", "id"]
        return [f"-{field}" for field in fields] if desc else fields


class IssueViewSet(AtomicRequestMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Issue.objects.filter(is_deleted=False).select_related("project")  # hide soft-deleted; router basename
    serializer_class = IssueSerializer
    pagination_class = IssuesCursorPagination
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return self.queryset

    # Require a project until the UI supports cross-project issue listing (#190).
    @token_guard("issues:read", guarding_project=lookup(query="project"))
    @extend_schema(
        summary="List issues",
        description="List issues for a project.",
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
                enum=["digest_order", "last_seen", "digested_event_count"],
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
    def list(self, request, project, *args, **kwargs):
        self.project = project
        return super().list(request, *args, **kwargs)

    @token_guard("issues:read", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Retrieve an issue",
        description="Retrieve an issue by issue UUID or friendly ID.",
        responses=IssueSerializer,
    )
    def retrieve(self, request, issue, *args, **kwargs):
        return Response(self.get_serializer(issue).data)

    @token_guard("issues:delete", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Delete an issue",
        description="Delete an issue.",
    )
    def destroy(self, request, issue, *args, **kwargs):
        issue.delete_deferred()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        return queryset.filter(project=self.project)

    def _action_response(self, issue):
        issue.save()
        return Response(self.get_serializer(issue).data)

    def _assert_unresolved(self, issue):
        if issue.is_resolved:
            raise ValidationError({"detail": "Issue is already resolved."})

    def _assert_resolved(self, issue):
        if not issue.is_resolved:
            raise ValidationError({"detail": "Issue is not resolved."})

    def _assert_unmuted(self, issue):
        if issue.is_muted:
            raise ValidationError({"detail": "Issue is already muted."})

    def _apply_issue_action(self, issue, action):
        # Bearer-token API auth currently represents a global token, not a user.
        apply_issue_action(IssueStateManager, issue, action, user=None)
        return self._action_response(issue)

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Resolve an issue",
        description="Mark this issue as resolved.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"])
    def resolve(self, request, issue, pk=None):
        self._assert_unresolved(issue)
        return self._apply_issue_action(issue, "resolve")

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Resolve an issue in the next release",
        description="Mark this issue as resolved by the next release.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"], url_path="resolve-next")
    def resolve_next(self, request, issue, pk=None):
        self._assert_unresolved(issue)
        return self._apply_issue_action(issue, "resolved_next")

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Resolve an issue in the latest release",
        description="Mark this issue as resolved in the latest release.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"], url_path="resolve-latest")
    def resolve_latest(self, request, issue, pk=None):
        self._assert_unresolved(issue)
        if not issue.project.has_releases:
            raise ValidationError({"detail": "Project has no releases."})

        latest_release = issue.project.get_latest_release()
        return self._apply_issue_action(issue, "resolved_release:" + latest_release.version)

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Reopen an issue",
        description="Mark this resolved issue as unresolved again.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"])
    def reopen(self, request, issue, pk=None):
        self._assert_resolved(issue)
        return self._apply_issue_action(issue, "reopen")

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Mute an issue",
        description="Mute this issue.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"])
    def mute(self, request, issue, pk=None):
        self._assert_unresolved(issue)
        self._assert_unmuted(issue)
        return self._apply_issue_action(issue, "mute")

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Mute an issue for a period",
        description="Mute this issue for a relative period, e.g. for 3 days.",
        request=IssueMuteForSerializer,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"], url_path="mute-for")
    def mute_for(self, request, issue, pk=None):
        serializer = IssueMuteForSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        period_name = serializer.validated_data["period_name"]
        nr_of_periods = serializer.validated_data["nr_of_periods"]

        self._assert_unresolved(issue)
        self._assert_unmuted(issue)
        return self._apply_issue_action(issue, f"mute_for:{period_name},{nr_of_periods},")

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Mute an issue until a threshold is reached",
        description="Mute this issue until a threshold is reached, e.g. more than 10 events in 1 hour.",
        request=IssueMuteUntilSerializer,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"], url_path="mute-until")
    def mute_until(self, request, issue, pk=None):
        serializer = IssueMuteUntilSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        period_name = serializer.validated_data["period_name"]
        nr_of_periods = serializer.validated_data["nr_of_periods"]
        gte_threshold = serializer.validated_data["gte_threshold"]

        self._assert_unresolved(issue)
        self._assert_unmuted(issue)
        return self._apply_issue_action(issue, f"mute_until:{period_name},{nr_of_periods},{gte_threshold}")

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Unmute an issue",
        description="Unmute this issue.",
        request=OpenApiTypes.NONE,
        responses=IssueSerializer,
    )
    @action(detail=True, methods=["post"])
    def unmute(self, request, issue, pk=None):
        self._assert_unresolved(issue)
        if not issue.is_muted:
            raise ValidationError({"detail": "Issue is not muted."})

        return self._apply_issue_action(issue, "unmute")


class IssueCommentViewSet(AtomicRequestMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = TurningPoint.objects.none()  # router basename only
    serializer_class = IssueCommentSerializer
    http_method_names = ["post", "head", "options"]

    @token_guard("issues:comment", guarding_issue=lookup(serializer="issue"))
    @extend_schema(
        summary="Create an issue comment",
        description="Add a comment to an issue. `issue` accepts an issue UUID or friendly ID.",
        request=IssueCommentSerializer,
        responses=IssueCommentSerializer,
    )
    def create(self, request, serializer, issue, *args, **kwargs):
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
