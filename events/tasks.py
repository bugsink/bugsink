from functools import partial
from django.db import transaction

from snappea.decorators import shared_task

from bugsink.transaction import immediate_atomic
from .storage_registry import get_storage

import logging

logger = logging.getLogger(__name__)


CLEANUP_BATCH_SIZE = 100  # TODO explain why


@shared_task
def clean_as_per_storage_cleanup_todos():
    from .models import StorageCleanupTodo

    with immediate_atomic():
        qs = StorageCleanupTodo.objects.all()[:CLEANUP_BATCH_SIZE]

        # evaluate in list to be unaffected by the subsequent delete
        todos = list(qs)
        StorageCleanupTodo.objects.filter(pk__in=[todo.pk for todo in todos]).delete()

        # we push the actual cleanup out of the transaction to avoid hogging the transaction for slow storage backends
        # (e.g.  S3); the tradeoffs are very similar to the on-write moment, where we make the same choice.
        transaction.on_commit(partial(_cleanup_on_storage, todos))

        if StorageCleanupTodo.objects.exists():
            # work remains, re-enqueue ourselves
            clean_as_per_storage_cleanup_todos.delay()


def _cleanup_on_storage(todos):
    performance_logger = logging.getLogger("bugsink.performance.db")  # TODO wrong!
    performance_logger.info("something that happens on_commit")
    for todo in todos:
        try:
            get_storage(todo.storage_backend).delete(todo.event_id)
        except Exception as e:
            # in a try/except such that we can continue with the rest of the batch
            logger.error("Error during cleanup of %s: %s", todo, e)
