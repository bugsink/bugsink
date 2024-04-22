import threading


class Workers:
    """Python's dict is 'probably thread safe', but since this is hard to reason about, and in fact .items() may be
    unsafe, we just use a lock. See e.g.

    * https://stackoverflow.com/questions/6953351/thread-safety-in-pythons-dictionary
    * https://stackoverflow.com/questions/66556511/is-listdict-items-thread-safe

    Furthermore: we need a way to do a Thread-safe update of what we actually have running, so worker_thread.start() is
    tied to the dict-update in a lock.
    """

    def __init__(self):
        self.d = {}
        self.lock = threading.Lock()

    def start(self, task_id, worker_thread):
        with self.lock:
            self.d[task_id] = worker_thread
            worker_thread.start()

    def stopped(self, task_id):
        with self.lock:
            del self.d[task_id]

    def list(self):
        with self.lock:
            return list(self.d.items())
