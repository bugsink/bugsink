import time
import random
import uuid
import logging

from .decorators import shared_task

logger = logging.getLogger("snappea.foreman")


@shared_task
def example_worker():
    me = str(uuid.uuid4())
    logger.info("example worker started %s", me)
    time.sleep(random.random() * 10)
    logger.info("example worker stopped %s", me)


@shared_task
def example_failing_worker():
    raise Exception("I am failing")
