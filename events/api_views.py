from rest_framework import viewsets

from .models import Event
from .serializers import EventSerializer


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Event.objects.all().order_by('digest_order')
    serializer_class = EventSerializer

    # TODO: the idea of required filter-fields when listing.
