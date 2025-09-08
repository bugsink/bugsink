from rest_framework import viewsets

from .models import Issue, Grouping
from .serializers import IssueSerializer, GroupingSerializer


class IssueViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Issue.objects.all().order_by('digest_order')  # TBD
    serializer_class = IssueSerializer


class GroupingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Grouping.objects.all().order_by('grouping_key')  # TBD
    serializer_class = GroupingSerializer

    # TODO: the idea of required filter-fields when listing.
