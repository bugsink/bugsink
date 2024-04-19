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
from .datastructures import SafeDict


GRACEFUL_TIMEOUT = 10
NUM_WORKERS = 4


logger = logging.getLogger("snappea.foreman")


class Foreman:
    """
    The Foreman starts workers, as (threading.Thread) threads, based on snappea.Task objects it finds in the sqlite
    database for that purpose (we use the DB as a simple MQ, we call this DBasMQ).

    The Foreman code itself is single-threaded, so it can be easily reasoned about.

    We provide an at-most-once guarantee: Tasks that are picked up are removed from the DB before the works starts.
    This fits with our model of background tasks, namely
    * things that you want to happen
    * but you don't want to wait for them in the request-response loop
    * getting them done for sure is not more important than in the server itself (which is also subject to os.kill)
    * you don't care about the answer as part of your code (of course, the DB can be affected)

    The read/writes to the DB-as-MQ are as such:

    * "some other process" (the HTTP server) writes _new_ Tasks
    * the Foreman reads Tasks (determines the workload)
    * the Foreman deletes (a write operation) Tasks (when done)

    Because the Foreman has a single sequential loop, and because it is the only thing that _updates_ tasks, there is no
    need for a locking model of some sort. sqlite locks the whole DB on-write, of course, but in this case we don't use
    that as a feature. The throughput of our MQ is limited by the speed with which we can do writes to sqlite (2 writes
    and 1 read are needed per task). I do not expect this to be in any way limiting (TODO check)

    The main idea is this endless loop of checking for new work and doing it. This leaves the question of how we "go to
    sleep" when there is no more work and how we wake up from that. This is implemented using [1] OS signals across
    processes (SIGUSR1 is sent from the 'client' after a Task object is created) and [2] a semaphore (to implement the
    wake-up on the main loop). Note that this idea is somewhat incidental though, I also considered polling in a busy
    loop or sending characters over a unix socket.

    Python signal handlers suspend whatever is currenlty going on (even other signal handlers). I find it hard to reason
    about that. This makes reasoning about what happens if they were to be interrupted both more likely and harder if
    they contain a lot of code. Solution: release a semaphore, that some other (sequentially looping) piece of code is
    waiting for.
    """

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
        # (we have implemented manual waiting for GRACEFUL_TIMEOUT separately).
        worker_thread.daemon = True
        worker_thread.start()
        self.workers.set(task_id, worker_thread)
        return worker_thread

    def handle_sigusr1(self, sig, frame):
        logger.debug("Received SIGUSR1")
        self.signal_semaphore.release()

    def handle_sigint(self, signal, frame):
        # We take the same approach as with handle SIGUSR1: we set a flag and release a semaphore. The advantage is that
        # we don't have to think about e.g. handle_sigint being called while we're handling a previous call to it. The
        # (slight) disadvantage is that we need to sprinkle calls to check_for_stopping() in more locations (at least
        # after every semaphore is acquired)
        logger.debug("Received SIGINT")

        if not self.stopping:  # without this if-statement, repeated signals would extend the deadline
            self.stopping = True
            self.stop_deadline = time.time() + GRACEFUL_TIMEOUT

        # Ensure that anything we might be waiting for is unblocked. A single .release call is enough because after
        # every acquire call in our codebase check_for_stopping() is the first thing we do, so the release cannot be
        # inadvertently be "used up" by something else.
        self.signal_semaphore.release()
        self.worker_semaphore.release()

    def run_forever(self):
        # Before we do our regular sleep-wake-check-do loop, we clear any outstanding work. sigusr1 signals coming in
        # during this time-period will simply "count up" the semaphore even though the work is already being done. This
        # is not really a problem, we'll just notice that there is "No task found" an equal amount of times and go into
        # deep sleep after.
        logger.info("Checking Task backlog")
        while self.create_worker():
            self.check_for_stopping()

        logger.info("Task backlog empty now, proceeding to main loop")
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

        # Loop over all tasks, waiting for them to finish. If they don't finish in time (GRACEFUL_TIMEOUT), we'll kill
        # them with a system-exit.
        for task_id, worker_thread in self.workers.list():
            if worker_thread.is_alive():
                time_left = self.stop_deadline - time.time()
                if time_left > 0:
                    logger.info("Waiting for worker %s", task_id)
                    worker_thread.join(time_left)
                    if worker_thread.is_alive():
                        logger.info("Worker %s did not die before the wait was over", task_id)
                else:
                    logger.info("No time left to wait for worker %s", task_id)  # it will be killed by system-exit

        logger.info("Foreman exit")
        sys.exit()
