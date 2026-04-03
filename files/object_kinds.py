from .models import File


OBJECT_KIND_SPECS = {
    "file": {
        "model": File,
        "key_field": "checksum",
    },
}


def get_object_kind_spec(object_kind):
    if object_kind not in OBJECT_KIND_SPECS:
        raise ValueError(f"Unknown object kind: {object_kind}")

    return OBJECT_KIND_SPECS[object_kind]
