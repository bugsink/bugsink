from django.apps import apps


OBJECT_KIND_SPECS = {
    "file": {
        "model": "files.File",
        "key_field": "checksum",
        "raw_data_getter": "get_raw_data",
        "data_field": "data",
    },
}


def get_object_kind_spec(object_kind):
    if object_kind not in OBJECT_KIND_SPECS:
        raise ValueError(f"Unknown object kind: {object_kind}")

    return OBJECT_KIND_SPECS[object_kind]


def get_object_kind_model(object_kind):
    return apps.get_model(get_object_kind_spec(object_kind)["model"])


def get_object_kind_for_model(model):
    for object_kind in OBJECT_KIND_SPECS:
        if get_object_kind_model(object_kind) == model:
            return object_kind

    raise ValueError(f"No object kind registered for model: {model}")


def get_object_storage_key(obj, object_kind):
    return getattr(obj, get_object_kind_spec(object_kind)["key_field"])


def get_object_storage_backend(obj):
    return obj.storage_backend


def set_object_stored_data(obj, object_kind, value):
    setattr(obj, get_object_kind_spec(object_kind)["data_field"], value)
