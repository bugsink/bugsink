from contextlib import contextmanager
import importlib

from bugsink.app_settings import get_settings, override_settings


_storages = None
_write_storages = None


def _ensure_storages():
    global _storages
    global _write_storages

    if _storages is not None:
        return

    _storages = {}
    _write_storages = {}

    for object_kind, object_kind_conf in get_settings().OBJECT_STORAGES.items():
        _storages[object_kind] = {
            name: _resolve(object_kind, name, conf)
            for name, conf in object_kind_conf.items()
        }

        matching = [name for name, conf in object_kind_conf.items() if conf.get("USE_FOR_WRITE", False)]

        if len(matching) == 1:
            _write_storages[object_kind] = _storages[object_kind][matching[0]]
        elif len(matching) > 1:
            raise ValueError(f"Multiple USE_FOR_WRITE storages found for {object_kind}.")
        else:
            _write_storages[object_kind] = None


def get_write_storage(object_kind):
    _ensure_storages()
    return _write_storages.get(object_kind)


def get_storage(object_kind, storage_name):
    _ensure_storages()
    return _storages[object_kind][storage_name]


def validate_storage_names(object_kind, storage_names):
    missing = []

    for storage_name in storage_names:
        try:
            get_storage(object_kind, storage_name)
        except KeyError:
            missing.append(storage_name)

    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Unknown storages found for {object_kind}: {missing_list}")


def _resolve(object_kind, name, conf):
    storage_name = conf["STORAGE"]

    module_name, class_name = storage_name.rsplit(".", 1)
    module = importlib.import_module(module_name)
    clazz = getattr(module, class_name)

    return clazz(name, object_kind=object_kind, **conf.get("OPTIONS", {}))


@contextmanager
def override_object_storages(storage_conf):
    global _storages
    global _write_storages

    _storages = None
    _write_storages = None

    try:
        with override_settings(OBJECT_STORAGES=storage_conf):
            yield
    finally:
        _storages = None
        _write_storages = None
