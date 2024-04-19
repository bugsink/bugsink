import json
import os
import logging
import time
import signal
import threading
from sentry_sdk import capture_exception

from . import registry
from .models import Pea


NUM_WORKERS = 2


logger = logging.getLogger("snappea.foreman")


def example_worker():
    import random
    me = str(random.random())
    logger.info("example worker started %s", me)
    time.sleep(10)
    logger.info("example worker stopped %s", me)


def example_failing_worker():
    raise Exception("I am failing")


class Foreman:

    def __init__(self):
        signal.signal(signal.SIGUSR1, self.handle_sigusr1)

        pid = os.getpid()
        logger.info("Foreman created, my pid is %s", pid)
        with open("/tmp/snappea.pid", "w") as f:   # TODO configurable location
            f.write(str(pid))

        # Counts the number of "wake up" signals that have not been dealt with yet. The main loop goes to sleep when
        # this is 0
        self.signal_semaphore = threading.Semaphore(0)

        # Counts the number of available worker threads. When this is 0, create_worker will first wait until a worker
        # stops. (the value of this semaphore is implicitly NUM_WORKERS - active_workers)
        self.worker_semaphore = threading.Semaphore(NUM_WORKERS)

    def run_in_thread(self, pea_id, function, *args, **kwargs):
        logger.info("run_in_thread: %s, %s.%s", pea_id, function.__module__, function.__name__)

        def non_failing_function(*inner_args, **inner_kwargs):
            try:
                function(*inner_args, **inner_kwargs)
            except Exception as e:
                # Potential TODO: make this configurable / depend on our existing config in bugsink/settings.py
                logger.info("Worker exception: %s", str(e))
                capture_exception(e)
            finally:
                logger.info("worker done: %s", pea_id)
                self.worker_semaphore.release()

        worker_thread = threading.Thread(target=non_failing_function, args=args, kwargs=kwargs)
        worker_thread.start()
        return worker_thread

    def handle_sigusr1(self, sig, frame):
        logger.info("Received SIGUSR1")
        self.signal_semaphore.release()

    def run_forever(self):
        while self.create_worker():
            pass

        while True:
            print("Checking (potentially waiting) for seen SIGUSR1")
            self.signal_semaphore.acquire()
            self.create_worker()

    def create_worker(self):
        """returns a boolean 'was anything done?'"""

        logger.info("Checking (potentially waiting) for available worker slots")
        self.worker_semaphore.acquire()

        pea = Pea.objects.first()
        if pea is None:
            # Seeing this is expected on-bootup (one after all Peas are dealt with, and once for each SIGUSR1 that was
            # received while clearing the initial backlog, but before we went into sleeping mode). If you see it later,
            # it's odd. (We could even assert for it)
            logger.info("No pea found")

            # We acquired the worker_semaphore at the start of this method, but we're not using it. Release immediately!
            self.worker_semaphore.release()
            return False

        # TODO note on why no transactions are needed (it's just a single call anyway)
        # TODO note on the guarantees we provide (not many)
        # TODO this bit is the main bit where an exception handler is missing: for both the (potentially failing) DB
        # write and the business of looking up tasks by name.
        pea_id = pea.id
        task = registry[pea.task_name]
        args = json.loads(pea.args)
        kwargs = json.loads(pea.kwargs)
        pea.delete()

        self.run_in_thread(pea_id, task, *args, **kwargs)

        return True
