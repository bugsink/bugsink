from django.db import migrations


def reset_quota_exceeded_until(apps, schema_editor):
    # Reset the quota_exceeded_until field for all Installation records. Since `quota_exceeded_until` is an optimization
    # (saves checkes) doing this is never "incorrect" (at the cost of one ingestion per project).
    # We do it here to ensure that there are no records with a value of `quota_exceeded_until` but without a value for
    # the new field `quota_exceeded_reason`. (from now on, the 2 will always be set together, but the field is new)

    Installation = apps.get_model("phonehome", "Installation")
    Installation.objects.filter(quota_exceeded_until__isnull=False).update(quota_exceeded_until=None)


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0004_installation_quota_exceeded_reason"),
    ]

    operations = [
        migrations.RunPython(reset_quota_exceeded_until, migrations.RunPython.noop),
    ]
