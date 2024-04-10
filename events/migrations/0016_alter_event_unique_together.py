from django.db import migrations
from django.db import models


def check_unique_together(apps, schema_editor):
    # manual check, allows for a pdb when this migration fails
    Event = apps.get_model('events', 'Event')

    for index in [('project', 'event_id'), ('issue', 'ingest_order')]:
        values = Event.objects.values(*index).annotate(count=models.Count('id')).filter(count__gt=1)
        if values:
            raise ValueError(f"Duplicate event_id values found: {values}")


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0008_set_project_slugs'),
        ('events', '0015_alter_event_ingest_order'),
    ]

    operations = [
        migrations.RunPython(check_unique_together),
        migrations.AlterUniqueTogether(
            name='event',
            unique_together={('project', 'event_id'), ('issue', 'ingest_order')},
        ),
    ]
