import contextlib
import os.path
from pathlib import Path


class EventStorage(object):

    def __init__(self, name, **options):
        self.name = name

    def save(self):
        raise NotImplementedError()

    def exists(self, event_id):
        raise NotImplementedError()

    def delete(self, event_id):
        raise NotImplementedError()

    def open(self, event_id):
        raise NotImplementedError()

    def list(self):
        raise NotImplementedError()

    # one might imagine contexts where something like "url" is useful (e.g. S3, and pointing the end-user straight at
    # the event file) but such a model means you'll need to think about the security implications of that URL, which is
    # not worth it, so we only support "pass through application layer" (where the auth stuff is) models of usage.


class FileEventStorage(EventStorage):

    def __init__(self, name, basepath=None):
        super().__init__(name)

        if basepath is None:
            raise ValueError("Basepath must be provided")

        self.basepath = basepath

    def _event_path(self, event_id):
        # the dashes in uuid are preserved in the filename for readability; since their location is consistent, this is
        # not a problem.
        return os.path.join(self.basepath, str(event_id) + ".json")

    @contextlib.contextmanager
    def open(self, event_id, mode='r'):
        if mode not in ('r', 'w'):
            # EventStorage's API is generally _very_ limited (unique IDs, write-once) so we can (and should) be very
            # strict about what we allow; we further imply "text mode" and "utf-8 encoding" given the JSON context.
            raise ValueError("EventStorage.open() mode must be 'r' or 'w'")

        if mode == 'w' and not os.path.exists(self.basepath):
            # only if we're writing does this make sense (when reading, a newly created directoy won't have files in it,
            # and fail in the next step)
            Path(self.basepath).mkdir(parents=True, exist_ok=True)

        # We open with utf-8 encoding explicitly to pre-empt the future of pep-0686 (it's also the only thing that makes
        # sense in the context of JSON)
        with open(self._event_path(event_id), mode, encoding="utf-8") as f:
            yield f

    def exists(self, event_id):
        return os.path.exists(self._event_path(event_id))

    def delete(self, event_id):
        os.remove(self._event_path(event_id))

    def list(self):
        # returns the event IDs (as strings) of all events in the storage. Useful for "cleanup" operations.
        # impl.: we use os.scandir() because it doesn't load the entire directory into memory (unlike os.listdir()), or
        # worse, sorts it. "Some people" point to pathlib.Path.iterdir() as a better alternative, but only since 3.12
        # is it using os.scandir(): https://github.com/python/cpython/commit/30f0643e36d2c9a5849c76ca0b27b748448d0567

        return (
            p.name[:-5]  # strip the ".json" suffix
            for p in os.scandir(self.basepath)
            if p.name.endswith(".json")
        )
