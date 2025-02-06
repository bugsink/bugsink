from django.db import migrations


def unfill_stored_event_count(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    Project.objects.all().update(stored_event_count=0)


def fill_stored_event_count(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    for project in Project.objects.all():
        project.stored_event_count = project.event_set.count()
        project.save()


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0010_project_stored_event_count"),
    ]

    operations = [
        migrations.RunPython(fill_stored_event_count, unfill_stored_event_count),
    ]
