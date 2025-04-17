from django.apps import apps
from django.utils import timezone

from snappea.decorators import shared_task

from bugsink.transaction import durable_atomic, immediate_atomic
from .models import CachedModelCount


@shared_task
def count_model(app_label, model_name):
    ModelClass = apps.get_model(app_label, model_name)

    # separate transaction for the expensive counting
    with durable_atomic():
        count = ModelClass.objects.count()

    with immediate_atomic():
        CachedModelCount.objects.update_or_create(
            app_label=app_label,
            model_name=model_name,
            defaults={
                'count': count,
                'last_updated': timezone.now(),
            },
        )
