import threading


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
