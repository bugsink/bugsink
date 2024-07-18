from django.utils import timezone

from projects.models import Project

from .models import Issue, Grouping
from .utils import get_issue_grouper_for_data


def get_or_create_issue(project=None, event_data=None):
    """create issue for testing purposes (code basically stolen from ingest/views.py)"""
    if event_data is None:
        from events.factories import create_event_data
        event_data = create_event_data()
    if project is None:
        project = Project.objects.create(name="Test project")

    grouping_key = get_issue_grouper_for_data(event_data)

    if not Grouping.objects.filter(project=project, grouping_key=grouping_key).exists():
        issue = Issue.objects.create(
            project=project,
            **denormalized_issue_fields(),
        )
        issue_created = True

        grouping = Grouping.objects.create(
            project=project,
            grouping_key=grouping_key,
            issue=issue,
        )

    else:
        grouping = Grouping.objects.get(project=project, grouping_key=grouping_key)
        issue = grouping.issue
        issue_created = False

    return issue, issue_created


def denormalized_issue_fields():
    """placeholder values for the "denormalized" (cached, calculated) fields on Issue for which there is no default"""
    return {
        "first_seen": timezone.now(),
        "last_seen": timezone.now(),
        "digested_event_count": 1,
    }
