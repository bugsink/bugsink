import os

from django.db import models

from .settings import get_settings
from . import thread_uuid


class Task(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    task_name = models.CharField(max_length=255)
    args = models.TextField(null=False, default='[]')
    kwargs = models.TextField(null=False, default='{}')

    def __str__(self):
        return self.task_name

    class Meta:
        indexes = [
            models.Index(fields=['created_at']),
        ]


class Stat(models.Model):
    timestamp = models.DateTimeField(null=False)
    task_name = models.CharField(max_length=255)
    task_count = models.PositiveIntegerField(null=True)  # null signifies "too much to count quickly"
    done = models.PositiveIntegerField(null=False)
    errors = models.PositiveIntegerField(null=False)
    wall_time = models.FloatField(null=False)
    wait_time = models.FloatField(null=False)
    write_time = models.FloatField(null=False)
    max_wall_time = models.FloatField(null=False)
    max_wait_time = models.FloatField(null=False)
    max_write_time = models.FloatField(null=False)

    class Meta:
        unique_together = (
            ('timestamp', 'task_name'),  # in this order, for efficient deletions
        )

    def __str__(self):
        return f"{self.timestamp.isoformat()[:16]} - {self.task_name}"


def wakeup_server():
    wakeup_file = os.path.join(get_settings().WAKEUP_CALLS_DIR, thread_uuid)

    if not os.path.exists(get_settings().WAKEUP_CALLS_DIR):
        os.makedirs(get_settings().WAKEUP_CALLS_DIR, exist_ok=True)

    if not os.path.exists(wakeup_file):
        with open(wakeup_file, "w"):
            pass
