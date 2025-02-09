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
        Max("digest_order"))["digest_order__max"]
    issue_digest_order = max_current + 1 if max_current is not None else 1

    # we get this via issue because we don't have manual merging yet; once we do, the following is more appropriate:
    # Grouping.objects.filter(project=project, grouping_key=grouping_key).get()
    grouping = issue.grouping_set.first()

    return Event.objects.create(
        project=project,
        issue=issue,
        grouping=grouping,
        ingested_at=timestamp,
        digested_at=timestamp,
        timestamp=timestamp,
        event_id=uuid.uuid4().hex,
        data=json.dumps(event_data),
        digest_order=issue_digest_order,
        irrelevance_for_retention=0,
    )


def create_event_data():
    # create minimal event data that is valid as per from_json()

    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": timezone.now().isoformat(),
        "platform": "python",
    }
