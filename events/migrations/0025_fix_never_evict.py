from django.db import migrations


def fix_never_evict(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    cnt = Event.objects.filter(never_evict=False, turningpoint__isnull=False).update(never_evict=True)
    if cnt:
        print(f"\nUpdated {cnt} Event records to set never_evict=True where turningpoint is not null.")


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0024_remove_event_debug_info"),
    ]

    operations = [
        migrations.RunPython(fix_never_evict, migrations.RunPython.noop),
    ]
