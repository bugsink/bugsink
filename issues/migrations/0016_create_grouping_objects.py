import json
from django.db import migrations

from issues.utils import get_issue_grouper_for_data


def create_grouping_objects(apps, schema_editor):
    Issue = apps.get_model('issues', 'Issue')
    Grouping = apps.get_model('issues', 'Grouping')

    for issue in Issue.objects.all():
        # we can do this because we know that there is at least one event, and because the events are already grouped
        # per issue (we just need to reconstruct the grouping key as implied by the hash)
        some_random_event = issue.event_set.first()
        event_data = json.loads(some_random_event.data)

        # we have _not_ inlined the code (which is standard good practice when creating datamigrations). Reason: this
        # data-migration is just here for my own development process, we don't need it to be perfect.
        grouping_key = get_issue_grouper_for_data(event_data)

        Grouping.objects.create(
            project=issue.project,
            issue=issue,
            grouping_key=grouping_key,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0015_remove_issue_hash_grouping'),
    ]

    operations = [
        migrations.RunPython(create_grouping_objects),
    ]
