import os
from bugsink.app_settings import get_settings


def get_filename_for_event_id(event_id):
    # TODO: the idea of having some levels of directories here (to avoid too many files in a single dir) is not yet
    # implemented.

    return os.path.join(get_settings().INGEST_STORE_BASE_DIR, event_id)
