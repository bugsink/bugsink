from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0008_set_project_slugs'),
        ('events', '0015_alter_event_ingest_order'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='event',
            unique_together={('project', 'event_id'), ('project', 'ingest_order')},
        ),
    ]
