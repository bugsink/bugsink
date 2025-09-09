from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from bugsink.utils import assert_

from .models import Event
from .serializers import EventListSerializer, EventDetailSerializer


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    LIST requires: ?issue=<uuid>
    Optional: ?order=asc|desc   (default: desc)
    LIST omits `data`, ordered by digest_order
    RETRIEVE includes `data` (pure PK lookup; no filters/order applied)
    """
    queryset = Event.objects.all()  # router requirement for basename inference
    serializer_class = EventListSerializer

    def filter_queryset(self, queryset):
        query_params = self.request.query_params

        if "issue" not in query_params:
            raise ValidationError({"issue": ["This field is required."]})

        order = query_params.get("order", "desc")
        if order not in ("asc", "desc"):
            raise ValidationError({"order": ["Must be 'asc' or 'desc'."]})

        ordering = "digest_order" if order == "asc" else "-digest_order"

        # (issue, digest_order) is a db-index
        return queryset.filter(issue=query_params["issue"]).order_by(ordering)

    def get_object(self):
        """
        DRF's get_object(), but we intentionally bypass filter_queryset for detail routes to keep PK lookups
        db-index-friendly (no WHERE filters other than the PK which is already indexed).
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
