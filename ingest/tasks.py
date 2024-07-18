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

    try:
        BaseIngestAPIView.digest_event(event_metadata, event_data)
    except ValidationError as e:
        logger.warning("ValidationError in digest_event", exc_info=e)
    finally:
        os.unlink(get_filename_for_event_id(event_id))
