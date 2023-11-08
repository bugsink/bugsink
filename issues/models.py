import json
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

    def parsed_data(self):
        # TEMP solution; won't scale
        return json.loads(self.events.first().data)

    def title(self):
        # TODO: refactor to a (filled-on-create) field
        parsed_data = json.loads(self.events.first().data)
        foo = parsed_data["exception"]["values"][0]
        return foo["type"] + ": " + foo["value"]
