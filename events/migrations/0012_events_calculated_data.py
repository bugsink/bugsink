import json

from django.db import migrations

from issues.utils import get_type_and_value_for_data


def fill_calculated_data(apps, schema_editor):
    # same caveats on lack of code copy-pasting, as well as the reasons these caveats probably don't matter, apply as in
    # the previous data-migration.

    Event = apps.get_model('events', 'Event')
    Issue = apps.get_model('issues', 'Issue')

    for event in Event.objects.all():
        event_data = json.loads(event.data)
        event.calculated_type, event.calculated_value = get_type_and_value_for_data(event_data)
        event.save()

    # this is for Issues, which is not in the same app, but who cares
    for issue in Issue.objects.all():
        event_data = json.loads(issue.event_set.first().data)
        issue.calculated_type, issue.calculated_value = get_type_and_value_for_data(event_data)
        issue.save()


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0011_event_calculated_type_event_calculated_value'),
    ]

    operations = [
        migrations.RunPython(fill_calculated_data, migrations.RunPython.noop),
    ]
