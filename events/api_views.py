from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse


from bugsink.utils import assert_
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
    """
    LIST requires: ?issue=<uuid>
    Optional: ?order=asc|desc   (default: desc)
    LIST omits `data`, ordered by digest_order
    RETRIEVE includes `data` (pure PK lookup; no filters/order applied)
    """
    queryset = Event.objects.all()  # router requirement for basename inference
    serializer_class = EventListSerializer
    pagination_class = EventPagination

    def filter_queryset(self, queryset):
        query_params = self.request.query_params

        if "issue" not in query_params:
            raise ValidationError({"issue": ["This field is required."]})

        return queryset.filter(issue=query_params["issue"])

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="issue",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Filter events by issue UUID (required).",
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
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_object(self):
        """
        DRF's get_object(), but we intentionally bypass filter_queryset for detail routes to keep PK lookups
        db-index-friendly (no WHERE filters other than the PK which is already indexed).
        # NOTE: alternatively, we just complain hard when a filter is applied to a detail view.
        """
        queryset = self.get_queryset()  # no filter_queryset() here

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        assert_(lookup_url_kwarg in self.kwargs, (
            'Expected view %s to be called with a URL keyword argument '
            'named "%s". Fix your URL conf, or set the `.lookup_field` '
            'attribute on the view correctly.' %
            (self.__class__.__name__, lookup_url_kwarg)
        ))

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        # May raise a permission denied
        self.check_object_permissions(self.request, obj)

        return obj

    def get_serializer_class(self):
        return EventDetailSerializer if self.action == "retrieve" else EventListSerializer

    @extend_schema(
        description="Render the event's stacktrace (frames, source, locals) as Markdown-like text.",
        responses={200: OpenApiResponse(response=str, description="Stacktrace as Markdown")},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stacktrace",
        renderer_classes=[MarkdownRenderer],
    )
    def stacktrace(self, request, pk=None):
        event = self.get_object()
        text = render_stacktrace_md(event, in_app_only=False, include_locals=True)
        return Response(text)
