import os
import glob

import uuid
import sys
import json
import logging
import time
import signal
import threading
from inotify_simple import INotify, flags
from sentry_sdk import capture_exception

from django.conf import settings

from . import registry
from .models import Task
from .datastructures import Workers
from .settings import get_settings


logger = logging.getLogger("snappea.foreman")


def short_id(task_id):
    # we take the least-significant 6 digits for task IDs when displaying them (for humans). This leaves the ability to
    # distinguish them meaningfully even when some tasks are processed a few orders of magnitude faster than others (not
    # expected) while at the same time processing _very many_ of the fast tasks. Upside: more readable logs.
    return f"{task_id:06}"[-6:-3] + "-" + f"{task_id:06}"[-3:]


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
    and at most 2 reads are needed per task (2 reads, because 1 to determine 'no more work'; when there are many items
    at the same time, the average amount of reads may be <1 because we read a whole list)). Performance on personal
    laptop: 1000 trivial tasks are finished enqueue-to-finished in a few seconds.

    The main idea is this endless loop of checking for new work and doing it. This leaves the question of how we "go to
    sleep" when there is no more work and how we wake up from that. This is implemented using inotify on a directory
    created specifically for that purpose (for each Task a file is dropped there) (and a blocking read on the INotify
    object). Note that this idea is somewhat incidental though (0MQ or polling the DB in a busy loop are some
    alternatives). Performance: write/inotify/delete of a single wake-up call is in the order of n*e-5 on my laptop.
    """

    def __init__(self):
        threading.current_thread().name = "FOREMAN"
        self.settings = get_settings()

        self.workers = Workers()
        self.stopping = False

        signal.signal(signal.SIGINT, self.handle_sigint)

        # We use inotify to wake up the Foreman when a new Task is created.
        if not os.path.exists(self.settings.WAKEUP_CALLS_DIR):
            os.makedirs(self.settings.WAKEUP_CALLS_DIR, exist_ok=True)
        self.wakeup_calls = INotify()
        self.wakeup_calls.add_watch(self.settings.WAKEUP_CALLS_DIR, flags.CREATE)

        # Pid stuff
        pid = os.getpid()

        logger.info(" =========  SNAPPEA  =========")
        logger.info("Startup: pid is %s", pid)
        logger.info("Startup: DB-as-MQ location: %s", settings.DATABASES["snappea"]["NAME"])
        logger.info("Startup: Wake up calls location: %s", self.settings.WAKEUP_CALLS_DIR)

        with open(self.settings.PID_FILE, "w") as f:
            f.write(str(pid))

        # Counts the number of "wake up" signals that have not been dealt with yet. The main loop goes to sleep when
        # this is 0
        self.signal_semaphore = threading.Semaphore(0)

        # Counts the number of available worker threads. When this is 0, create_workers will first wait until a worker
        # stops. (the value of this semaphore is implicitly NUM_WORKERS - active_workers)
        self.worker_semaphore = threading.Semaphore(self.settings.NUM_WORKERS)

    def run_in_thread(self, task_id, function, *args, **kwargs):
        # NOTE: we expose args & kwargs in the logs; as it stands no sensitive stuff lives there in our case, but this
        # is something to keep an eye on
        logger.info(
            'Starting %s for "%s.%s" with %s, %s',
            short_id(task_id), function.__module__, function.__name__, args, kwargs)

        def non_failing_function(*inner_args, **inner_kwargs):
            t0 = time.time()
            try:
                function(*inner_args, **inner_kwargs)
            except Exception as e:
                # Potential TODO: make this configurable / depend on our existing config in bugsink/settings.py
                logger.warning("Snappea caught Exception: %s", str(e))
                capture_exception(e)
            finally:
                logger.info("Worker done in %.3fs", time.time() - t0)
                self.workers.stopped(task_id)
                self.worker_semaphore.release()

        worker_thread = threading.Thread(
            target=non_failing_function, args=args, kwargs=kwargs, name=f"{short_id(task_id)}")

        # killing threads seems to be 'hard'(https://stackoverflow.com/questions/323972/is-there-any-way-to-kill-a-thre)
        # we can, however, set deamon=True which will ensure that an exit of the main thread is the end of the program
        # (we have implemented manual waiting for GRACEFUL_TIMEOUT separately).
        worker_thread.daemon = True

        self.workers.start(task_id, worker_thread)
        return worker_thread

    def handle_sigint(self, signal, frame):
        # We set a flag and release a semaphore. The advantage is that we don't have to think about e.g. handle_sigint
        # being called while we're handling a previous call to it. The (slight) disadvantage is that we need to sprinkle
        # calls to check_for_stopping() in more locations (at least after every semaphore is acquired)
        logger.debug("Received SIGINT")  # NOTE: calling logger in handle_xxx is probably a bad idea

        if not self.stopping:  # without this if-statement, repeated signals would extend the deadline
            self.stopping = True
            self.stop_deadline = time.time() + self.settings.GRACEFUL_TIMEOUT

        # Ensure that anything we might be waiting for is unblocked. A single notification file and .release call is
        # enough because after every wakeup_calls.read() /  acquire call in our codebase the first thing we do is
        # check_for_stopping(), so the release cannot be inadvertently be "used up" by something else.
        with open(os.path.join(self.settings.WAKEUP_CALLS_DIR, str(uuid.uuid4())), "w"):
            pass
        self.worker_semaphore.release()

    def run_forever(self):
        pre_existing_wakeup_notifications = glob.glob(os.path.join(self.settings.WAKEUP_CALLS_DIR, "*"))
        if len(pre_existing_wakeup_notifications) > 0:
            # We clear the wakeup_calls_dir on startup. Not strictly necessary because such files would be cleared by in
            # the loop anyway, but it's more efficient to do it first.
            logger.info("Startup: Clearing %s items from wakeup dir", len(pre_existing_wakeup_notifications))
            for filename in pre_existing_wakeup_notifications:
                os.remove(filename)

        # Before we do our regular sleep-wake-check-do loop, we clear any outstanding work. wake up signals coming in
        # during this time-period will simply "count up" the semaphore even though the work is already being done. This
        # is not really a problem, we'll just notice that there is "No task found" an equal amount of times and go into
        # deep sleep after.
        logger.info("Startup: Clearing Task backlog")
        while self.create_workers() == self.settings.TASK_QS_LIMIT:
            # `== TASK_QS_LIMIT` means we may have more work to do, because the [:TASK_QS_LIMIT] slice may be the reason
            # no more work is found. We keep doing this until we're sure there is no more work to do.
            pass

        logger.info("Startup: Task backlog empty now, proceeding to main loop")
        while True:
            logger.debug("Main loop: Waiting for wakeup call")
            for event in self.wakeup_calls.read():
                logger.debug("Main loop: Removing wakeup notification %s", event.name)
                # I think we can just do os.unlink(), without being afraid of an error either here or on the side where
                # we write the file. I don't have a link to the man page to back this up, but when running "many" calls
                # (using 2 processes with each simple tight loop, one creating the files and one deleting them, I did
                # not get any errors)
                os.unlink(os.path.join(self.settings.WAKEUP_CALLS_DIR, event.name))

            self.check_for_stopping()  # always check after .read()
            while self.create_workers() == self.settings.TASK_QS_LIMIT:
                pass  # `== TASK_QS_LIMIT`: as documented above

    def create_workers(self):
        """returns the number of workers created (AKA tasks done)"""

        logger.debug("Main loop: Querying for tasks")
        # We get "a lot" of Tasks at once, rather than one by one. We assume (but did not test) this is more efficient
        # than getting the Tasks one by one. It also has consequences for the case where many Tasks (and thus
        # wakeup notifications) come in at the same time: in such cases, we may deal with more than one Task for a
        # single iteration through run_forever's while loop. The final loop before sleeping will then have a "No task
        # found" (and associated useless READ on the database). Why we do this: the .all() approach works with how we
        # deal with wake up notifications, namely: whenever we get some, we .read() (and delete) all of them away in one
        # swoop. This means a number of notifications will fold into a single iteration through our main run_forever
        # loop and thus we need to do more than a single Task. Also, the waisted READ is precisely when there is nothing
        # to do (i.e. it's waisting time when we have a lot of time).

        # (we've put _some_ limit on the amount of tasks to get in a single query to avoid memory overflows when there
        # is a lot of work. the expected case is: when the snappeaserver has been gone for a while, and work has been
        # built up in the backlog; we want to at least be resilient for that case.)
        tasks = Task.objects.all()[:self.settings.TASK_QS_LIMIT]

        task_i = -1
        for task_i, task in enumerate(tasks):
            logger.debug("Main loop: Creating worker for with task %s", short_id(task.id))
            logger.debug("Main loop: Checking (maybe waiting) for available worker slots")
            self.worker_semaphore.acquire()
            logger.debug("Main loop: Worker slot available")
            self.check_for_stopping()  # always check after .acquire()

            # TODO note on why no transactions are needed (it's just a single call anyway)
            # TODO note on the guarantees we provide (not many)
            # TODO this bit is the main bit where an exception handler is missing: for both the (potentially failing) DB
            # write and the business of looking up tasks by name.
            task_id = task.id
            function = registry[task.task_name]
            args = json.loads(task.args)
            kwargs = json.loads(task.kwargs)

            self.check_for_stopping()  # check_for_stopping() right before taking on the work
            task.delete()
            self.run_in_thread(task_id, function, *args, **kwargs)

        task_count = task_i + 1

        # Seeing "0 tasks..." is expected, both on Startup and right before we go into "Wait for wakeup". See also
        # above, starting with 'We get "a lot" of Tasks at once'
        logger.debug("Main loop: %s tasks popped from queue and started as workers ", task_count)
        return task_count

    def check_for_stopping(self):
        if not self.stopping:
            return
        logger.info("Stopping")

        # Loop over all tasks, waiting for them to finish. If they don't finish in time (GRACEFUL_TIMEOUT), we'll kill
        # them with a system-exit.
        for task_id, worker_thread in self.workers.list():
            if worker_thread.is_alive():
                time_left = self.stop_deadline - time.time()
                if time_left > 0:
                    worker_thread.join(time_left)
                    if worker_thread.is_alive():
                        logger.info(
                            "Stopping: %s did not die in %.1fs, proceeding to kill",
                            short_id(task_id), self.settings.GRACEFUL_TIMEOUT)
                else:
                    # for the logs distinguishing between "explicit join targets" and "not dead yet" is irrelevant, we
                    # use the same format.
                    logger.info(
                        "Stopping: %s did not die in %.1fs, proceeding to kill",
                        short_id(task_id), self.settings.GRACEFUL_TIMEOUT)

        logger.info("Stopping: EXIT")

        sys.exit()
