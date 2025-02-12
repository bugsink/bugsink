from contextlib import contextmanager
import importlib

from bugsink.app_settings import get_settings, override_settings


_storages = None
_write_storage = None


def _ensure_storages():
    global _storages
    global _write_storage

    if _storages is not None:
        return

    _storages = {name: _resolve(name, conf) for name, conf in get_settings().EVENT_STORAGES.items()}

    matching = [name for name, conf in get_settings().EVENT_STORAGES.items() if conf.get("USE_FOR_WRITE", False)]

    if len(matching) == 1:
        _write_storage = _storages[matching[0]]

    elif len(matching) > 1:
        raise ValueError("Multiple USE_FOR_WRITE storages found.")

    # else len==0 is implied by the initial value of _write_storage (None)


def get_write_storage():
    """
    Gets the USE_FOR_WRITE storage. None means "in-database" (which is not shoe-horned in the EventStorage API).
    """
    _ensure_storages()
    return _write_storage


def get_storage(storage_name):
    _ensure_storages()
    return _storages[storage_name]


def _resolve(name, conf):
    storage_name = conf["STORAGE"]

    module_name, class_name = storage_name.rsplit('.', 1)
    module = importlib.import_module(module_name)
    clazz = getattr(module, class_name)

    return clazz(name, **conf.get("OPTIONS", {}))


@contextmanager
def override_event_storages(storage_conf):
    """
    Temporarily override the event storage for the duration of the context (for tests).
    """
    global _storages
    global _write_storage

    _storages = None
    _write_storage = None

    try:
        with override_settings(EVENT_STORAGES=storage_conf):
            yield

    finally:
        _storages = None
        _write_storage = None
