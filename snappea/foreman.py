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
        logger.info("Received signal, starting new thread")
        self.run_in_thread(example_failing_worker)
        # worker_thread = threading.Thread(target=example_worker)

        lll.append("x")
        me = len(lll)
        for i in range(4):
            print("am I locked?", me, i)
            time.sleep(1)

    def run_forever(self):
        # there is no actual code here, all the action happens in the signal handlers
        while True:
            time.sleep(3600)
