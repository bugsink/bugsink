import json
import uuid

from django.db import models
from django.utils import timezone
from bugsink.transaction import immediate_atomic

from bugsink.app_settings import get_settings

EMAIL_ATTEMPTS_MAX = 10


class Installation(models.Model):
    # "Installation" would probably be better at home in some different app, especially now that we're adding more and
    # more stuff to it. But cross-app migrations are annoying enough and the upside is _very_ limited so it stays here.

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    silence_email_system_warning = models.BooleanField(default=False)

    # ingestion/digestion quota
    email_quota_usage = models.TextField(null=False, default='{"per_month": {}}')
    email_sending_diagnostics = models.TextField(null=False, default='{"attempts": []}')
    quota_exceeded_until = models.DateTimeField(null=True, blank=True)
    quota_exceeded_reason = models.CharField(max_length=255, null=False, default="null")
    next_quota_check = models.PositiveIntegerField(null=False, default=0)

    @classmethod
    # minimalize write-lock-hogging (while being callable within atomic blocks; i.e. we accept that we lose the "is
    # outer" guarantee (that would be very nice for email sending) to be able to run from inside TASK_ALWAYS_EAGER
    # tasks.
    @immediate_atomic(only_if_needed=True)
    def check_and_inc_email_quota(cls, date):
        obj = cls.objects.first()

        email_quota_usage = json.loads(obj.email_quota_usage)

        hour_key = date.strftime('%Y-%m-%dT%H')
        if hour_key not in email_quota_usage.get("per_hour", {}):
            email_quota_usage['per_hour'] = {hour_key: 0}  # full overwrite: no need to keep old info around.

        month_key = date.strftime('%Y-%m')
        if month_key not in email_quota_usage["per_month"]:
            email_quota_usage['per_month'] = {month_key: 0}  # full overwrite: no need to keep old info around.

        if (get_settings().MAX_EMAILS_PER_HOUR is not None
                and email_quota_usage['per_hour'][hour_key] >= get_settings().MAX_EMAILS_PER_HOUR):
            return False

        if (get_settings().MAX_EMAILS_PER_MONTH is not None
                and email_quota_usage['per_month'][month_key] >= get_settings().MAX_EMAILS_PER_MONTH):
            return False

        email_quota_usage['per_hour'][hour_key] += 1
        email_quota_usage['per_month'][month_key] += 1

        obj.email_quota_usage = json.dumps(email_quota_usage)
        obj.save()
        return True

    @classmethod
    # minimalize write-lock-hogging (while being callable within atomic blocks; i.e. we accept that we lose the "is
    # outer" guarantee (that would be very nice for email sending) to be able to run from inside TASK_ALWAYS_EAGER
    # tasks.
    @immediate_atomic(only_if_needed=True)
    def record_email_attempt(cls, ok, duration, error=None, attempted_at=None):
        obj = cls.objects.first()

        diagnostics = json.loads(obj.email_sending_diagnostics)
        attempt = {
            "at": (attempted_at or timezone.now()).isoformat(),
            "ok": ok,
            "duration": round(duration, 3),
        }
        if error is not None:
            attempt["error"] = str(error)[:100]

        attempts = diagnostics.get("attempts", [])
        attempts.append(attempt)
        diagnostics["attempts"] = attempts[-EMAIL_ATTEMPTS_MAX:]

        obj.email_sending_diagnostics = json.dumps(diagnostics)
        obj.save(update_fields=["email_sending_diagnostics"])


class OutboundMessage(models.Model):
    attempted_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True)
    message = models.TextField()

    def __str__(self):
        return f"OutboundMessage(attempted_at={self.attempted_at}, sent_at={self.sent_at})"
