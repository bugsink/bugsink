from django.db import migrations


def remove_objects_with_null_issue(apps, schema_editor):
    # Up until now, we have various models w/ .issue=FK(null=True, on_delete=models.SET_NULL)
    # Although it is "not expected" in the interface, issue-deletion would have led to those
    # objects with a null issue. We're about to change that to .issue=FK(null=False, ...) which
    # would crash if we don't remove those objects first. Object-removal is "fine" though, because
    # as per the meaning of the SET_NULL, these objects were "dangling" anyway.

    Grouping = apps.get_model("issues", "Grouping")
    TurningPoint = apps.get_model("issues", "TurningPoint")

    Grouping.objects.filter(issue__isnull=True).delete()
    TurningPoint.objects.filter(issue__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0019_alter_grouping_grouping_key_hash"),
    ]

    operations = [
        migrations.RunPython(remove_objects_with_null_issue, reverse_code=migrations.RunPython.noop),
    ]
