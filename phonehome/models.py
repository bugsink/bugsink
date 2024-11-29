import uuid

from django.db import models


class Installation(models.Model):
    # "Installation" would probably be better at home in some different app, especially now that we're adding more and
    # more stuff to it. But cross-app migrations are annoying enough and the upside is _very_ limited so it stays here.

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    silence_email_system_warning = models.BooleanField(default=False)


class OutboundMessage(models.Model):
    attempted_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True)
    message = models.TextField()

    def __str__(self):
        return f"OutboundMessage(attempted_at={self.attempted_at}, sent_at={self.sent_at})"
