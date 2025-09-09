from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from .models import Issue, Grouping
from .serializers import IssueSerializer, GroupingSerializer


class IssueViewSet(viewsets.ReadOnlyModelViewSet):
    """
    LIST requires: ?project=<uuid>
    Optional: ?order=asc|desc        (default: desc)
    LIST ordered by last_seen
    RETRIEVE is a pure PK lookup (soft-deletes implied)
    """
    queryset = Issue.objects.filter(is_deleted=False)  # hide soft-deleted issues; also satisfies router
    serializer_class = IssueSerializer

    def get_queryset(self):
        return self.queryset

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        query_params = self.request.query_params

        project = query_params.get("project")
        if not project:
            # the below until we have a UI for cross-project Issue listing, i.e. #190
            raise ValidationError({"project": ["This field is required."]})

        order = query_params.get("order", "desc")
        if order not in ("asc", "desc"):
            raise ValidationError({"order": ["Must be 'asc' or 'desc'."]})

        ordering = "last_seen" if order == "asc" else "-last_seen"
        return queryset.filter(project=project).order_by(ordering)

    def get_object(self):
        """
        DRF's get_object(), but bypass filter_queryset for detail.
        """
        # TODO: copy/paste from events/api_views.py
        queryset = self.get_queryset()

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        assert lookup_url_kwarg in self.kwargs, (
            'Expected view %s to be called with a URL keyword argument named "%s".'
            % (self.__class__.__name__, lookup_url_kwarg)
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj


class GroupingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Grouping.objects.all().order_by('grouping_key')  # TBD
    serializer_class = GroupingSerializer

    # TODO: the idea of required filter-fields when listing.
