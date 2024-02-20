import uuid

from django.utils import timezone

from projects.models import Project

from .models import Issue
from .utils import get_hash_for_data


def get_or_create_issue(project=None, event_data=None):
    """create issue for testing purposes (code basically stolen from ingest/views.py)"""
    if event_data is None:
        event_data = create_event_data()
    if project is None:
        project = Project.objects.create(name="Test project")

    hash_ = get_hash_for_data(event_data)
    issue, issue_created = Issue.objects.get_or_create(
        project=project,
        hash=hash_,
        defaults=denormalized_issue_fields(),
    )
    return issue, issue_created


def create_event_data():
    """create minimal event data that is valid as per from_json()"""

    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": timezone.now().isoformat(),
        "platform": "python",
    }


def denormalized_issue_fields():
    """return a dict of fields that are expected to be denormalized on Issue; for testing purposes"""
    return {
        "first_seen": timezone.now(),
        "last_seen": timezone.now(),
        "event_count": 1,
    }
