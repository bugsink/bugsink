import logging
import os.path
from pathlib import Path

from django.utils._os import safe_join


logger = logging.getLogger("bugsink.objectstorage")


class ObjectStorage:
    def __init__(self, name, object_kind, **options):
        self.name = name
        self.object_kind = object_kind

    def exists(self, key):
        raise NotImplementedError()

    def delete(self, key):
        raise NotImplementedError()

    def open(self, key, mode):
        raise NotImplementedError()

    def list(self):
        raise NotImplementedError()


class ObjectFileStorage(ObjectStorage):
    def __init__(self, name, object_kind, basepath=None, get_basepath=None, **kwargs):
        super().__init__(name, object_kind)

        if (basepath is None) == (get_basepath is None):
            raise ValueError("Provide exactly one of basepath or get_basepath")

        if get_basepath is not None:
            self.get_basepath = get_basepath
        else:
            self.get_basepath = lambda object_kind: basepath

        if kwargs:
            logger.warning("ObjectFileStorage ignored unexpected arguments: %s", ", ".join(kwargs.keys()))

    def _path(self, key):
        return safe_join(self.get_basepath(self.object_kind), str(key))

    def open(self, key, mode="rb"):
        if mode not in ("rb", "wb"):
            raise ValueError("ObjectFileStorage.open() mode must be 'rb' or 'wb'")

        if mode == "wb" and not os.path.exists(self.get_basepath(self.object_kind)):
            Path(self.get_basepath(self.object_kind)).mkdir(parents=True, exist_ok=True)

        return open(self._path(key), mode)

    def exists(self, key):
        return os.path.exists(self._path(key))

    def delete(self, key):
        os.remove(self._path(key))

    def list(self):
        if not os.path.exists(self.get_basepath(self.object_kind)):
            return []

        return (p.name for p in os.scandir(self.get_basepath(self.object_kind)))
