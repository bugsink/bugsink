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
    if "ingestion_id" in event_metadata:
        ingestion_id = event_metadata["ingestion_id"]  # the normal case
    else:
        ingestion_id = event_id  # for bugsink<=2.0.11 events in-transit in snappea queue cross version upgrade

    with open(get_filename_for_event_id(ingestion_id), "rb") as f:
        event_data = json.loads(f.read().decode("utf-8"))
        opened = [get_filename_for_event_id(ingestion_id)]

    if event_metadata.get("has_minidump"):
        with open(get_filename_for_event_id(ingestion_id, filetype="minidump"), "rb") as f:
            minidump_bytes = f.read()
            opened += [get_filename_for_event_id(ingestion_id, filetype="minidump")]
    else:
        minidump_bytes = None

    try:
        BaseIngestAPIView.digest_event(event_metadata, event_data, minidump_bytes=minidump_bytes)
    except ValidationError as e:
        logger.warning("ValidationError in digest_event", exc_info=e)
    finally:
        # "Robustly" remove all opened files (don't stop on failure), but still report any errors at the end
        errors = []
        for filename in opened:
            try:
                os.unlink(filename)
            except FileNotFoundError as e:
                errors.append(e)
        if errors:
            raise Exception(errors)
