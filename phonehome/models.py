import json
import uuid

from django.db import models
from bugsink.transaction import immediate_atomic

from bugsink.app_settings import get_settings


class Installation(models.Model):
    # "Installation" would probably be better at home in some different app, especially now that we're adding more and
    # more stuff to it. But cross-app migrations are annoying enough and the upside is _very_ limited so it stays here.

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    silence_email_system_warning = models.BooleanField(default=False)

    # ingestion/digestion quota
    email_quota_usage = models.TextField(null=False, default='{"per_month": {}}')
    quota_exceeded_until = models.DateTimeField(null=True, blank=True)
    quota_exceeded_reason = models.CharField(max_length=255, null=False, default="null")
    next_quota_check = models.PositiveIntegerField(null=False, default=0)

    @classmethod
    @immediate_atomic(only_if_needed=True)  # minimalize write-lock-hogging (while being callable within atomic blocks)
    def check_and_inc_email_quota(cls, date):
        obj = cls.objects.first()

        email_quota_usage = json.loads(obj.email_quota_usage)

        key = date.strftime('%Y-%m')
        if key not in email_quota_usage["per_month"]:
            email_quota_usage['per_month'] = {key: 0}  # full overwrite: no need to keep old info around.

        if (get_settings().MAX_EMAILS_PER_MONTH is not None
                and email_quota_usage['per_month'][key] >= get_settings().MAX_EMAILS_PER_MONTH):
            return False

        email_quota_usage['per_month'][key] += 1

        obj.email_quota_usage = json.dumps(email_quota_usage)
        obj.save()
        return True


class OutboundMessage(models.Model):
    attempted_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True)
    message = models.TextField()

    def __str__(self):
        return f"OutboundMessage(attempted_at={self.attempted_at}, sent_at={self.sent_at})"
