from django.db import migrations


def unfill_stored_event_count(apps, schema_editor):
    Issue = apps.get_model("issues", "Issue")
    Issue.objects.all().update(stored_event_count=0)


def fill_stored_event_count(apps, schema_editor):
    Issue = apps.get_model("issues", "Issue")
    for issue in Issue.objects.all():
        issue.stored_event_count = issue.event_set.count()
        issue.save()


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0008_issue_stored_event_count"),
    ]

    operations = [
        migrations.RunPython(fill_stored_event_count, unfill_stored_event_count),
    ]
