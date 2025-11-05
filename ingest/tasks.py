import os
import logging
import json

from django.core.exceptions import ValidationError

from snappea.decorators import shared_task

from .filestore import get_filename_for_event_id

logger = logging.getLogger("bugsink.ingest")


@shared_task
def digest(event_id, event_metadata):
    from .views import BaseIngestAPIView

    with open(get_filename_for_event_id(event_id), "rb") as f:
        event_data = json.loads(f.read().decode("utf-8"))

    if event_metadata.get("has_minidump"):
        with open(get_filename_for_event_id(event_id, filetype="minidump"), "rb") as f:
            minidump_bytes = f.read()
    else:
        minidump_bytes = None

    try:
        BaseIngestAPIView.digest_event(event_metadata, event_data, minidump_bytes=minidump_bytes)
    except ValidationError as e:
        logger.warning("ValidationError in digest_event", exc_info=e)
    finally:
        # NOTE: if an SDK misbehaves, and sends the same event_id multiple times in quick succession, the line below
        # will trigger a FileNotFoundError on the second attempt to delete the file (the files also overwrite each other
        # on-ingest). In that case your logs will also a "ValidationError in digest_event". Although that means an error
        # bubbles up from the below, at least for now I'm OK with that. (next steps _could_ be: [a] catching the error
        # as expected [b] refusing to "just overwrite and doubly enqueue on-ingest" [c] reporting about this particular
        # problem to the end-user etc... but at least "getting it really right" might actually be quite hard (race
        # conditions) and I'm not so sure it's worth it.
        os.unlink(get_filename_for_event_id(event_id))
