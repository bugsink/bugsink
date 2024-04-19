import os
import logging
import time
import signal
import threading
from sentry_sdk import capture_exception


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

        # self.workers = []

        pid = os.getpid()
        logger.info("Foreman created, my pid is %s", pid)
        with open("/tmp/snappea.pid", "w") as f:
            f.write(str(pid))

        self.semaphore = threading.Semaphore(0)
        self.worker_semaphore = threading.Semaphore(NUM_WORKERS)

    def run_in_thread(self, function, *args, **kwargs):
        def non_failing_function(*inner_args, **inner_kwargs):
            try:
                function(*inner_args, **inner_kwargs)
            except Exception as e:
                # Potential TODO: make this configurable / depend on our existing config in bugsink/settings.py
                logger.info("Worker exception: %s", str(e))
                capture_exception(e)
            finally:
                self.worker_semaphore.release()

        worker_thread = threading.Thread(target=non_failing_function, *args, **kwargs)
        worker_thread.start()
        return worker_thread

    def handle_sigusr1(self, sig, frame):
        logger.info("Received signal")
        self.semaphore.release()

    def run_forever(self):
        while True:
            print("Waiting for semaphore")
            self.semaphore.acquire()
            self.step()

    def step(self):
        print("STEP")
        print("worker_semaphore.acquire()")
        self.worker_semaphore.acquire()
        # self.workers.append is a TODO
        print("run in thread")
        self.run_in_thread(example_worker)
        print("OK")
