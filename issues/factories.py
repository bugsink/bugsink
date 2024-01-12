import uuid

from django.utils import timezone

from .models import Issue
from .utils import get_hash_for_data


def get_or_create_issue(project, event_data):
    # create issue for testing purposes (code basically stolen from ingest/views.py)
    hash_ = get_hash_for_data(event_data)
    issue, issue_created = Issue.objects.get_or_create(
        project=project,
        hash=hash_,
    )
    return issue, issue_created


def create_event_data():
    # create minimal event data that is valid as per from_json()

    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": timezone.now().isoformat(),
        "platform": "python",
    }
