import os

from django.db import models

from .settings import get_settings
from . import thread_uuid


class Task(models.Model):
    task_name = models.CharField(max_length=255)
    args = models.TextField(null=False, default='[]')
    kwargs = models.TextField(null=False, default='{}')

    def __str__(self):
        return self.task_name


def wakeup_server():
    wakeup_file = os.path.join(get_settings().WAKEUP_CALLS_DIR, thread_uuid)

    if not os.path.exists(get_settings().WAKEUP_CALLS_DIR):
        os.makedirs(get_settings().WAKEUP_CALLS_DIR, exist_ok=True)

    if not os.path.exists(wakeup_file):
        with open(wakeup_file, "w"):
            pass
