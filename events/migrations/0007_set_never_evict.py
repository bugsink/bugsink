from django.db import migrations


def set_never_evict(apps, schema_editor):
    Event = apps.get_model('events', 'Event')
    Event.objects.filter(turningpoint__isnull=False).update(never_evict=True)


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0006_event_never_evict'),
        ('issues', '0003_alter_turningpoint_triggering_event'),
    ]

    operations = [
        migrations.RunPython(set_never_evict, migrations.RunPython.noop),
    ]
