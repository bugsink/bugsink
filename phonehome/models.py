import uuid

from django.db import models


class Installation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)


class OutboundMessage(models.Model):
    attempted_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True)
    message = models.TextField()

    def __str__(self):
        return f"OutboundMessage(attempted_at={self.attempted_at}, sent_at={self.sent_at})"
