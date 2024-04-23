import time
import random
import logging

from .decorators import shared_task

# for the example tasks, we pick a non-snappea logger on purpose, to check that non-snappea logs are written in the
# correct format when the snappea server is running (in general, logs inside tasks will have non-snappea loggers)
logger = logging.getLogger("bugsink")


@shared_task
def random_duration():
    logger.info("Starting something of a random duration")
    time.sleep(random.random() * 10)


@shared_task
def failing_task():
    raise Exception("I am failing")


@shared_task
def fast_task():
    pass
