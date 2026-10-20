import os
import logging
import json

from django.core.exceptions import ValidationError
from django.utils import timezone

from snappea.decorators import shared_task
from phonehome.models import Installation
from projects.models import Project

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
        # Quota-shedding must be done before immediate_atomic is entered such that it can be done in parallel, see #494
        project = Project.objects.filter(pk=event_metadata["project_id"], is_deleted=False).first()
        if project is not None and project.get_retention_max_event_count() != 0:
            # count != 0 to skip this optimization such that the special case can be dealt with inside `digest_event`
            now = timezone.now()
            installation = Installation.objects.get()
            if (BaseIngestAPIView.is_quota_still_exceeded(installation, now)
                    or BaseIngestAPIView.is_quota_still_exceeded(project, now)):
                return

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
