from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from bugsink.api_mixins import AtomicRequestMixin
from bugsink.api_capabilities import lookup, token_guard
from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_authorization import enforce_project_boundness, enforce_user_boundness_for_project
from projects.models import Project, get_issue_accessible_project_ids
from tags.search import search_issues
from events.api_counts import EventCountRangeSerializer, EventCountsSerializer, event_counts_response
from events.models import IssueEventCountsPerHour

from .models import Issue, IssueStateManager, TurningPoint, apply_issue_action
from .serializers import (
    GroupingSerializer,
    IssueCommentSerializer,
    IssueMuteForSerializer,
    IssueMuteUntilSerializer,
    IssueSerializer,
    IssueTagSerializer,
    TurningPointSerializer,
)


ISSUE_ID_PARAMETER = OpenApiParameter(
    name="id",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    required=True,
    description="Issue UUID or friendly ID (e.g. PROJECT-123).",
)


class IssueRelatedPagination(CursorPagination):
    ordering = "id"
    page_size = 250


class IssuesCursorPagination(CursorPagination):
    """
    Cursor paginator for /issues supporting ?sort=… and ?order=asc|desc.

    Sort modes are named after the *primary* column:
      - sort=digest_order         → unique per project → no tie-breakers needed
      - sort=last_seen            → timestamp          → tie-breaker on id
      - sort=digested_event_count → lifetime count     → tie-breakers on last_seen and id

    Direction applies to primary *and beyond* (i.e. all fields in the list).
    digest_order requires a single project; global lists default to last_seen.
    """
    # With a single project, digest_order uses the (project_id, digest_order) index and is cursor-stable.

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
        single_project = view.project is not None
        sort = request.query_params.get("sort", self.default_sort if single_project else "last_seen")
        if sort not in self.VALID_SORTS:
            raise ValidationError({
                "sort": ["Must be 'digest_order', 'last_seen', or 'digested_event_count'."],
            })

        order = request.query_params.get("order", self.default_direction if single_project else "desc")
        if order not in self.VALID_ORDERS:
            raise ValidationError({"order": ["Must be 'asc' or 'desc'."]})

        desc = (order == "desc")

        if sort == "digest_order":
            if not single_project:
                raise ValidationError({"sort": ["digest_order requires a single project."]})
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

    @token_guard("issues:read", scopable_by_bound_project=True)
    @extend_schema(
        summary="List issues",
        description=(
            "List issues across accessible projects, optionally limited to one project. "
            "Project-bound tokens stay within their project; personal tokens require accepted project membership "
            "(superusers can access all projects). Deleted issues and projects are excluded."
        ),
        parameters=[
            OpenApiParameter(
                name="project",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter issues by project ID. Omit to list all projects accessible to the token.",
            ),
            OpenApiParameter(
                name="q",
                type=OpenApiTypes.STR,
                description=(
                    "Search titles as plain text and filter tags with `key:value`; quote values containing spaces. "
                    "Results must match the text and every tag filter."
                ),
            ),
            OpenApiParameter(
                name="state",
                type=OpenApiTypes.STR,
                enum=["all", "open", "unresolved", "resolved", "muted"],
                description="Filter by issue state (default: all). Open means neither resolved nor muted.",
            ),
            OpenApiParameter(
                name="sort",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["digest_order", "last_seen", "digested_event_count"],
                description="Default: digest_order for a single project, last_seen across projects. "
                            "digest_order requires a single project.",
            ),
            OpenApiParameter(
                name="order",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["asc", "desc"],
                description="Default: asc for a single project, desc across projects.",
            ),
        ]
    )
    def list(self, request, bound_project, *args, **kwargs):
        self.project = bound_project
        if "project" in request.query_params:
            self.project = get_object_or_404(
                Project.objects.filter(is_deleted=False), pk=request.query_params["project"])
        if self.project is not None:
            self.check_object_permissions(request, self.project)
            enforce_project_boundness(request.auth, self.project)
            enforce_user_boundness_for_project(request.auth, "issues:read", self.project)
        return super().list(request, *args, **kwargs)

    @token_guard("issues:read", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Retrieve an issue",
        description="Retrieve an issue by issue UUID or friendly ID.",
        parameters=[ISSUE_ID_PARAMETER],
        responses=IssueSerializer,
    )
    def retrieve(self, request, issue, *args, **kwargs):
        return Response(self.get_serializer(issue).data)

    @token_guard("events:read", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="List issue tag values and counts",
        description=(
            "List stored tag values and their occurrence counts, ordered by ID. "
            "Counts are not reduced when event payloads are evicted. "
            "Includes values the UI groups under Other or hides as mostly unique."
        ),
        parameters=[
            ISSUE_ID_PARAMETER,
            OpenApiParameter(name="key", type=OpenApiTypes.STR, description="Filter by exact tag key."),
        ],
        responses=IssueTagSerializer(many=True),
    )
    @action(detail=True, methods=["get"], serializer_class=IssueTagSerializer, pagination_class=IssueRelatedPagination)
    def tags(self, request, issue, pk=None):
        queryset = issue.tags.select_related("key", "value")
        if "key" in request.query_params:
            queryset = queryset.filter(key__key=request.query_params["key"])
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @token_guard("events:read", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="List issue grouping keys",
        description="List the grouping keys and mechanisms associated with this issue, ordered by ID.",
        parameters=[ISSUE_ID_PARAMETER],
        responses=GroupingSerializer(many=True),
    )
    @action(detail=True, methods=["get"], serializer_class=GroupingSerializer, pagination_class=IssueRelatedPagination)
    def grouping(self, request, issue, pk=None):
        page = self.paginate_queryset(issue.grouping_set.all())
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @token_guard("issues:read", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Retrieve issue event counts",
        description=(
            "Hourly counts by digest time, including evicted events. Empty hours have count zero. "
            "Defaults to 24 hours, including the incomplete current hour. "
            "Ranges must use UTC hour boundaries and fall within the last 90 days."
        ),
        parameters=[ISSUE_ID_PARAMETER, EventCountRangeSerializer],
        responses=EventCountsSerializer,
    )
    @action(detail=True, methods=["get"], url_path="event-counts", pagination_class=None)
    def event_counts(self, request, issue, pk=None):
        return event_counts_response(IssueEventCountsPerHour.objects.filter(issue=issue), request.query_params)

    @token_guard("issues:delete", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Delete an issue",
        description="Delete an issue.",
        parameters=[ISSUE_ID_PARAMETER],
    )
    def destroy(self, request, issue, *args, **kwargs):
        issue.delete_deferred()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        state = self.request.query_params.get("state", "all")
        state_filters = {
            "all": {},
            "open": {"is_resolved": False, "is_muted": False},
            "unresolved": {"is_resolved": False},
            "resolved": {"is_resolved": True, "is_muted": False},
            "muted": {"is_resolved": False, "is_muted": True},
        }
        if state not in state_filters:
            raise ValidationError({"state": ["Must be 'all', 'open', 'unresolved', 'resolved', or 'muted'."]})

        queryset = queryset.filter(project__is_deleted=False, **state_filters[state])
        if self.project is not None:
            queryset = queryset.filter(project=self.project)
        elif self.request.auth.is_user_bound:
            queryset = queryset.filter(project_id__in=get_issue_accessible_project_ids(self.request.auth.user))
        return search_issues(self.project, queryset, self.request.query_params.get("q", "").strip())

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
        apply_issue_action(IssueStateManager, issue, action, user=None)
        return self._action_response(issue)

    @token_guard("issues:triage", guarding_issue=lookup(url="pk"))
    @extend_schema(
        summary="Resolve an issue",
        description="Mark this issue as resolved.",
        parameters=[ISSUE_ID_PARAMETER],
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
        parameters=[ISSUE_ID_PARAMETER],
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
        parameters=[ISSUE_ID_PARAMETER],
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
        parameters=[ISSUE_ID_PARAMETER],
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
        parameters=[ISSUE_ID_PARAMETER],
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
        parameters=[ISSUE_ID_PARAMETER],
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
        parameters=[ISSUE_ID_PARAMETER],
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
        parameters=[ISSUE_ID_PARAMETER],
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


class IssueHistoryPagination(AscDescCursorPagination):
    # Timestamps are not unique (one digest can produce several turning points), so id breaks ties.
    base_ordering = ("timestamp", "id")
    page_size = 250
    default_direction = "desc"  # newest first, aligned with the UI's history tab


class IssueHistoryViewSet(AtomicRequestMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = TurningPoint.objects.select_related("user")
    serializer_class = TurningPointSerializer
    pagination_class = IssueHistoryPagination

    def filter_queryset(self, queryset):
        return queryset.filter(issue=self.issue)

    @token_guard("issues:read", guarding_issue=lookup(query="issue"))
    @extend_schema(
        summary="List issue history",
        description="List the turning points (state changes and comments) of an issue.",
        parameters=[
            OpenApiParameter(
                name="issue",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Filter history by issue UUID or friendly ID (required).",
            ),
            OpenApiParameter(
                name="order",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["asc", "desc"],
                description="Sort order of timestamp (default: desc).",
            ),
        ]
    )
    def list(self, request, issue, *args, **kwargs):
        self.issue = issue
        return super().list(request, *args, **kwargs)
