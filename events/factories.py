import json
import uuid

from django.utils import timezone
from django.db.models import Max

from issues.factories import get_or_create_issue
from .models import Event


def create_event(project=None, issue=None, timestamp=None, event_data=None):
    if issue is None:
        issue, _ = get_or_create_issue(project, event_data)

    if project is None:
        project = issue.project

    if timestamp is None:
        timestamp = timezone.now()

    if event_data is None:
        event_data = create_event_data()

    max_current = Event.objects.filter(project=project).aggregate(
        Max("ingest_order"))["ingest_order__max"]
    issue_ingest_order = max_current + 1 if max_current is not None else 1

    return Event.objects.create(
        project=project,
        issue=issue,
        server_side_timestamp=timestamp,
        timestamp=timestamp,
        event_id=uuid.uuid4().hex,
        has_exception=True,
        has_logentry=True,
        data=json.dumps(event_data),
        ingest_order=issue_ingest_order,
    )


def create_event_data():
    # create minimal event data that is valid as per from_json()

    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": timezone.now().isoformat(),
        "platform": "python",
    }
