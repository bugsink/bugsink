from django.db import models


class Pea(models.Model):
    task_name = models.CharField(max_length=255)
    args = models.TextField(null=False, default='[]')
    kwargs = models.TextField(null=False, default='{}')

    def __str__(self):
        return self.task_name
