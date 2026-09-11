from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiTypes, OpenApiResponse


from bugsink.api_capabilities import lookup, token_guard
from bugsink.api_pagination import AscDescCursorPagination
from bugsink.api_mixins import AtomicRequestMixin

from .models import Event
from .serializers import EventListSerializer, EventDetailSerializer
from .markdown_stacktrace import render_stacktrace_md
from .renderers import MarkdownRenderer


class EventPagination(AscDescCursorPagination):
    # Cursor pagination requires an indexed, mostly-stable ordering field. We use `digest_order`: we require
    # ?issue=<uuid> and have a composite (issue_id, digest_order) index, so ORDER BY digest_order after filtering by
    # issue is fast and cursor-stable. (also note that digest_order comes in in-order).
    base_ordering = ("digest_order",)
    page_size = 250
    default_direction = "desc"  # newest first by default, aligned with UI


class EventViewSet(AtomicRequestMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Event.objects.all()  # router requirement for basename inference
    serializer_class = EventListSerializer
    pagination_class = EventPagination

    def filter_queryset(self, queryset):
        return queryset.filter(issue=self.issue)

    @token_guard("events:read", guarding_issue=lookup(query="issue"))
    @extend_schema(
        summary="List events",
        description="List events for an issue. The list response omits the full event `data` payload.",
        parameters=[
            OpenApiParameter(
                name="issue",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Filter events by issue UUID or friendly ID (required).",
            ),
            OpenApiParameter(
                name="order",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["asc", "desc"],
                description="Sort order of digest_order (default: desc).",
            ),
        ]
    )
    def list(self, request, issue, *args, **kwargs):
        self.issue = issue
        return super().list(request, *args, **kwargs)

    @token_guard("events:read", guarding_event=lookup(url="pk"))
    @extend_schema(
        summary="Retrieve an event",
        description=(
            "Retrieve an event by internal Bugsink event UUID. "
            "The detail response includes the full `data` payload."
        ),
        responses=EventDetailSerializer,
    )
    def retrieve(self, request, event, *args, **kwargs):
        return Response(self.get_serializer(event).data)

    def get_serializer_class(self):
        return EventDetailSerializer if self.action == "retrieve" else EventListSerializer

    @token_guard("events:read", guarding_event=lookup(url="pk"))
    @extend_schema(
        summary="Render an event stacktrace",
        description="Render the event's stacktrace (frames, source, locals) as Markdown-like text.",
        responses={
            200: OpenApiResponse(
                response=str,
                description="Stacktrace as Markdown",
                examples=[
                    OpenApiExample(
                        "Stacktrace",
                        value="Traceback (most rece...",
                        response_only=True,
                    ),
                ],
            )
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stacktrace",
        renderer_classes=[MarkdownRenderer],
    )
    def stacktrace(self, request, event, pk=None):
        text = render_stacktrace_md(event, in_app_only=False, include_locals=True)
        return Response(text)
