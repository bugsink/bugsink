import json
import uuid

from django.utils import timezone

from events.models import Event


def create_event(project, issue, timestamp=None, event_data=None):
    if timestamp is None:
        timestamp = timezone.now()

    if event_data is None:
        event_data = create_event_data()

    return Event.objects.create(
        project=project,
        issue=issue,
        server_side_timestamp=timestamp,
        timestamp=timestamp,
        event_id=uuid.uuid4().hex,
        has_exception=True,
        has_logentry=True,
        data=json.dumps(event_data),
        ingest_order=0,
    )


def create_event_data():
    # create minimal event data that is valid as per from_json()

    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": timezone.now().isoformat(),
        "platform": "python",
    }
