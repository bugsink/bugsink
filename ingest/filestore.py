import uuid
import os
from bugsink.app_settings import get_settings


def get_filename_for_event_id(event_id):
    # The idea of having some levels of directories here (to avoid too many files in a single dir) is not yet
    # implemented. However, counterpoint: when doing stress tests, it was quite hard to get a serious backlog going
    # (snappea was very well able to play catch-up). So this might not be necessary.

    # ensure that event_id is a uuid, and remove dashes if present; also doubles as a security-check (event_id is
    # user-provided (but at this point already validated to be a valid UUID), but b/c of the below the
    # security-implications of os.path.join can be understood right here in the code without needing to inspect all
    # call-sites).
    event_id_normalized = uuid.UUID(event_id).hex

    return os.path.join(get_settings().INGEST_STORE_BASE_DIR, event_id_normalized)
