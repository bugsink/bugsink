import os
import logging
import time
import signal
import threading
from sentry_sdk import capture_exception


logger = logging.getLogger("snappea.foreman")


def example_worker():
    logger.info("example worker started")
    time.sleep(10)
    logger.info("example worker stopped")


def example_failing_worker():
    raise Exception("I am failing")


lll = []


class Foreman:

    def __init__(self):
        # signal.signal(signal.SIGTERM, self.handle_sigterm)  later
        signal.signal(signal.SIGUSR1, self.handle_sigusr1)

        self.workers = []

        pid = os.getpid()
        logger.info("Foreman created, my pid is %s", pid)
        with open("/tmp/snappea.pid", "w") as f:
            f.write(str(pid))

        self.semaphore = threading.Semaphore(0)

    def handle_sigterm(self, sig, frame):
        print("Handling SIGTERM signal")

    def run_in_thread(self, function, *args, **kwargs):
        def non_failing_function(*inner_args, **inner_kwargs):
            try:
                function(*inner_args, **inner_kwargs)
            except Exception as e:
                # Potential TODO: make this configurable / depend on our existing config in bugsink/settings.py
                logger.info("Worker exception: %s", str(e))
                capture_exception(e)

        worker_thread = threading.Thread(target=non_failing_function, *args, **kwargs)
        worker_thread.run()
        return worker_thread

    def handle_sigusr1(self, sig, frame):
        logger.info("Received signal")

        lll.append("x")
        me = len(lll)
        for i in range(4):
            print("am I locked A?", me, i)
            time.sleep(1)

        self.semaphore.release()

        for i in range(4):
            print("am I locked B?", me, i)
            time.sleep(1)

    def run_forever(self):
        while True:
            print("Waiting for semaphore")
            self.semaphore.acquire()
            self.step()

    def step(self):
        print("STEP")
        """
        self.run_in_thread(example_failing_worker)
        # worker_thread = threading.Thread(target=example_worker)

        """
