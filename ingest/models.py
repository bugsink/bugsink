import uuid

from django.db import models
from django.utils import timezone

from projects.models import Project


class DecompressedEvent(models.Model):   # or... DecompressedRawEvent... or just IngestedEvent
    """Ingested Event, no processing"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    data = models.TextField(blank=False, null=False)
    timestamp = models.DateTimeField(null=False, default=timezone.now, help_text="Server-side timestamp")

    # filled with values from the http header X-Bugsink-Debug-Info; for now this is duplicated across
    # Event/DecompressedEvent; we'll have to figure out which of the 2 models is the right one to put it in (this
    # relates to the question of whether we want to keep the raw data around)
    # (at the very least I want it here, because in the setup with split up ingest/digest, we need to store it here to
    # be able to have it available when we digest)
    debug_info = models.CharField(max_length=255, blank=True, null=False, default="")
