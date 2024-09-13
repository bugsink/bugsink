import os
from bugsink.app_settings import get_settings


def get_filename_for_event_id(event_id):
    # The idea of having some levels of directories here (to avoid too many files in a single dir) is not yet
    # implemented. However, counterpoint: when doing stress tests, it was quite hard to get a serious backlog going
    # (snappea was very well able to play catch-up). So this might not be necessary.

    return os.path.join(get_settings().INGEST_STORE_BASE_DIR, event_id)
