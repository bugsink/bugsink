import sys
import json
import os
import logging
import time
import signal
import threading
from sentry_sdk import capture_exception

from . import registry
from .models import Task
from .decorators import shared_task


GRACEFUL_TIMEOUT = 10
NUM_WORKERS = 4


logger = logging.getLogger("snappea.foreman")


@shared_task
def example_worker():
    import random
    import uuid
    me = str(uuid.uuid4())
    logger.info("example worker started %s", me)
    time.sleep(random.random() * 10)
    logger.info("example worker stopped %s", me)


@shared_task
def example_failing_worker():
    raise Exception("I am failing")


class SafeDict:
    """Python's dict is 'probably thread safe', but since this is hard to reason about, and in fact .items() may be
    unsafe, we just use a lock. See e.g.
    * https://stackoverflow.com/questions/6953351/thread-safety-in-pythons-dictionary
    * https://stackoverflow.com/questions/66556511/is-listdict-items-thread-safe
    """

    def __init__(self):
        self.d = {}
        self.lock = threading.Lock()

    def set(self, k, v):
        with self.lock:
            self.d[k] = v

    def unset(self, k):
        with self.lock:
            del self.d[k]

    def list(self):
        with self.lock:
            return list(self.d.items())


class Foreman:

    def __init__(self):
        self.workers = SafeDict()
        self.stopping = False

        signal.signal(signal.SIGINT, self.handle_sigint)
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

    def run_in_thread(self, task_id, function, *args, **kwargs):
        logger.info("run_in_thread: %s, %s.%s", task_id, function.__module__, function.__name__)

        def non_failing_function(*inner_args, **inner_kwargs):
            try:
                function(*inner_args, **inner_kwargs)
            except Exception as e:
                # Potential TODO: make this configurable / depend on our existing config in bugsink/settings.py
                logger.info("Worker exception: %s", str(e))
                capture_exception(e)
            finally:
                logger.info("worker done: %s", task_id)
                self.workers.unset(task_id)
                self.worker_semaphore.release()

        worker_thread = threading.Thread(target=non_failing_function, args=args, kwargs=kwargs)

        # killing threads seems to be 'hard'(https://stackoverflow.com/questions/323972/is-there-any-way-to-kill-a-thre)
        # we can, however, set deamon=True which will ensure that an exit of the main thread is the end of the program
        # (and then implement some manual waiting separately).
        worker_thread.daemon = True
        worker_thread.start()
        self.workers.set(task_id, worker_thread)
        return worker_thread

    def handle_sigint(self, signal, frame):
        # Note: a more direct way is available (just put the stopping in the sigint) but I think the indirection is
        # easier to think about.
        logger.debug("Received SIGINT")
        self.stopping = True

        # ensure that anything we might be waiting for is unblocked
        self.signal_semaphore.release()
        self.worker_semaphore.release()

    def handle_sigusr1(self, sig, frame):
        logger.debug("Received SIGUSR1")
        self.signal_semaphore.release()

    def run_forever(self):
        logger.info("Checking Task backlog")
        while self.create_worker():
            self.check_for_stopping()

        while True:
            logger.debug("Checking (potentially waiting) for SIGUSR1")
            self.signal_semaphore.acquire()
            self.check_for_stopping()
            self.create_worker()

    def create_worker(self):
        """returns a boolean 'was anything done?'"""

        logger.debug("Checking (potentially waiting) for available worker slots")
        self.worker_semaphore.acquire()
        self.check_for_stopping()  # always check after .acquire()

        task = Task.objects.first()
        if task is None:
            # Seeing this is expected on-bootup (one after all Peas are dealt with, and once for each SIGUSR1 that was
            # received while clearing the initial backlog, but before we went into sleeping mode). If you see it later,
            # it's odd. (We could even assert for it)
            logger.info("No task found")

            # We acquired the worker_semaphore at the start of this method, but we're not using it. Release immediately!
            self.worker_semaphore.release()
            return False

        # TODO note on why no transactions are needed (it's just a single call anyway)
        # TODO note on the guarantees we provide (not many)
        # TODO this bit is the main bit where an exception handler is missing: for both the (potentially failing) DB
        # write and the business of looking up tasks by name.
        task_id = task.id
        function = registry[task.task_name]
        args = json.loads(task.args)
        kwargs = json.loads(task.kwargs)

        self.check_for_stopping()
        task.delete()
        self.run_in_thread(task_id, function, *args, **kwargs)

        return True

    def check_for_stopping(self):
        if not self.stopping:
            return
        logger.info("Foreman stopping")

        deadline = time.time() + GRACEFUL_TIMEOUT
        for task_id, worker_thread in self.workers.list():
            if worker_thread.is_alive():
                time_left = deadline - time.time()
                if time_left > 0:
                    logger.info("Waiting for worker %s", task_id)
                    worker_thread.join(time_left)
                    if worker_thread.is_alive():
                        logger.info("Worker %s did not die before the wait was over", task_id)
                else:
                    logger.info("No time left to wait for worker %s", task_id)  # it will be killed by system-exit

        logger.info("Foreman exit")
        sys.exit()
