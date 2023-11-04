import uuid

from django.db import models

from projects.models import Project


class DecompressedEvent(models.Model):
    """Ingested Event, no processing"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    data = models.TextField(blank=False, null=False)
    timestamp = models.DateTimeField(null=False, auto_now_add=True, help_text="Server-side timestamp")

    def get_absolute_url(self):
        # same note about misplacement as the view this is pointing to
        return "/events/event/%s/" % self.id
