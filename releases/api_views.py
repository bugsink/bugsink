from rest_framework import viewsets

from .models import Release
from .serializers import ReleaseSerializer


class ReleaseViewSet(viewsets.ModelViewSet):
    queryset = Release.objects.all().order_by('sort_epoch')
    serializer_class = ReleaseSerializer

    # TODO: the idea of required filter-fields when listing; in particular: project is required.
