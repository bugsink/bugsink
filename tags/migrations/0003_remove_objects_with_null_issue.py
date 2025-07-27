from django.db import migrations


def remove_objects_with_null_issue(apps, schema_editor):
    # Up until now, we have various models w/ .issue=FK(null=True, on_delete=models.SET_NULL)
    # Although it is "not expected" in the interface, issue-deletion would have led to those
    # objects with a null issue. We're about to change that to .issue=FK(null=False, ...) which
    # would crash if we don't remove those objects first. Object-removal is "fine" though, because
    # as per the meaning of the SET_NULL, these objects were "dangling" anyway.

    EventTag = apps.get_model("tags", "EventTag")
    IssueTag = apps.get_model("tags", "IssueTag")

    EventTag.objects.filter(issue__isnull=True).delete()
    IssueTag.objects.filter(issue__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tags", "0002_no_cascade"),
    ]

    operations = [
        migrations.RunPython(remove_objects_with_null_issue, reverse_code=migrations.RunPython.noop),
    ]
