import os
import logging
import json

from django.core.exceptions import ValidationError
from django.utils import timezone

from bugsink.app_settings import get_settings
from snappea.decorators import shared_task
from phonehome.models import Installation
from projects.models import Project
from sentry.minidump import merge_minidump_event

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
        project = Project.objects.filter(pk=event_metadata["project_id"], is_deleted=False).first()
        if project is None:
            return
        if BaseIngestAPIView.handle_zero_retention(project):
            return

        # Quota-shedding must be done before immediate_atomic is entered such that it can be done in parallel, see #494
        # NOTE `now` is separate from `digested_at` in digest_event. Does that mean clock-differences lead to shedding
        # too much? No: if this were so, it would only be so by virtue of the quota expiring b/c our processing was
        # delayed. Also realise: any event literally arriving (at ingest) _now_ would also not make it.
        # The reverse case also works (checking early cannot let an event bypass the quota: digest_event checks again)
        now = timezone.now()
        installation = Installation.objects.get()
        if (BaseIngestAPIView.is_quota_still_exceeded(installation, now)
                or BaseIngestAPIView.is_quota_still_exceeded(project, now)):
            return

        if get_settings().VALIDATE_ON_DIGEST in ["warn", "strict"]:
            BaseIngestAPIView.validate_event_data(event_data, get_settings().VALIDATE_ON_DIGEST)

        if minidump_bytes is not None:
            # we merge after validation: validation is about what's provided _externally_, not our own merging.
            # We parse before entering immediate_atomic so this work doesn't hold the database write lock.
            # TODO error handling
            merge_minidump_event(event_data, minidump_bytes, project)

        BaseIngestAPIView.digest_event(event_metadata, event_data)
    except ValidationError as e:
        logger.warning("ValidationError in digest", exc_info=e)
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
