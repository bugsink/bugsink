import os
import logging
import time
import signal
import threading
from sentry_sdk import capture_exception

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
        with open("/tmp/snappea.pid", "w") as f:
            f.write(str(pid))

        self.semaphore = threading.Semaphore(0)
        self.worker_semaphore = threading.Semaphore(NUM_WORKERS)

    def run_in_thread(self, pea_id, function, *args, **kwargs):
        logger.info("run_in_thread: %s, %s", pea_id, function)

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

        worker_thread = threading.Thread(target=non_failing_function, *args, **kwargs)
        worker_thread.start()
        return worker_thread

    def handle_sigusr1(self, sig, frame):
        logger.info("Received signal")
        self.semaphore.release()

    def run_forever(self):
        while self.create_worker():
            pass

        while True:
            print("Waiting for semaphore")
            self.semaphore.acquire()
            self.create_worker()

    def create_worker(self):
        """returns a boolean 'was anything done?'"""

        logger.info("worker_semaphore.acquire()")
        self.worker_semaphore.acquire()

        pea = Pea.objects.first()
        if pea is None:
            logger.info("no Pea found")
            self.worker_semaphore.release()
            return False

        # TODO note on why no transactions are needed (it's just a single call anyway)
        # TODO note on the guarantees we provide
        pea_id = pea.id
        pea.delete()
        self.run_in_thread(pea_id, example_worker)

        return True
