import uuid
import logging
import threading


logger = logging.getLogger("snappea.foreman")


class Registry:
    def __init__(self):
        self.registry = {}

    def __setitem__(self, key, value):
        self.registry[key] = value

    def __getitem__(self, key):
        if key not in self.registry:
            logger.debug(f"Task '{key}' not found in registry. Trying to import the module.")
            if key.count('.') == 0:
                raise ValueError(f'Task name "{key}" is not in the format "module[s].function".')
            module_name, function = key.rsplit('.', 1)
            try:
                # importing the module will register the task if it has the shared_task decorator
                __import__(module_name, globals(), locals(), [function])
            except ImportError:
                logging.debug(f"Import failed for {module_name}.")

        return self.registry[key]


registry = Registry()

# We use a random filename for wakeup_file, but it is random only for the sending thread. This has the advantage that
# when many wakeup signals are sent but not consumed they will not fill up our wakeup_calls_dir in O(n) fashion. This
# filling-up could otherwise happen, because the Foreman takes on some chunk of work from the DB (currently: 100
# records) which may take a while to be processed (especially if this value is larger than the number of workers) and
# the wake up signals may flood the wakeup_dir in that time.
#
# Using a single file per-client does not introduce race conditions, though this is much harder to see than for the
# file-per-task case. To see why this is the case (TODO copy notes from paper, including those for the previous case)
#
# (The fact that this is hard to see could provide an argument for reverting to per-task-uuid; to keep the directory
# from overflowing we would have to make the batch-size (much) smaller. (we cannot just put signal cleanups inside the
# worker-creation loop, because they always need to precede the querying for tasks).
#
# Note that our current solution (less than one wake-up signal per task) has moved us away from "everything as files"
# (i.e. tied us stronger to actually maintaining the queue in sqlite)
localStorage = threading.local()
localStorage.uuid = str(uuid.uuid4())
thread_uuid = localStorage.uuid
