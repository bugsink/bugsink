from rest_framework import viewsets

from .models import Team
from .serializers import TeamSerializer


class TeamViewSet(viewsets.ReadOnlyModelViewSet):  # create? then we need a way to deal with visibility
    queryset = Team.objects.all().order_by('name')  # ordering: TBD
    serializer_class = TeamSerializer
