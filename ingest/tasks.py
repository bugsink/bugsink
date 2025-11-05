import contextlib
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
        opened = [get_filename_for_event_id(event_id)]

    if event_metadata.get("has_minidump"):
        with open(get_filename_for_event_id(event_id, filetype="minidump"), "rb") as f:
            minidump_bytes = f.read()
            opened += [get_filename_for_event_id(event_id, filetype="minidump")]
    else:
        minidump_bytes = None

    try:
        BaseIngestAPIView.digest_event(event_metadata, event_data, minidump_bytes=minidump_bytes)
    except ValidationError as e:
        logger.warning("ValidationError in digest_event", exc_info=e)
    finally:
        # NOTE: if an SDK misbehaves, and sends the same event_id multiple times in quick succession, the os.unlink
        # below will trigger a FileNotFoundError on the second attempt to delete the file (the events also overwrite
        # each other on-ingest, but that's separately dealt with, showing a "ValidationError in digest_event". We're
        # just catching those and ignoring them (bubble-up is not desirable because it hinders follow-up cleanups)
        for filename in opened:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(filename)
