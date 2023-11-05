import uuid
from django.db import models


class Issue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    project = models.ForeignKey(
        "projects.Project", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    hash = models.CharField(max_length=32, blank=False, null=False)
    events = models.ManyToManyField("ingest.DecompressedEvent")

    def get_absolute_url(self):
        return f"/issues/issue/{ self.id }/events/"
