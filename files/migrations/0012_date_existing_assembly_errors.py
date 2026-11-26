from django.db import migrations
from django.utils import timezone


def date_existing_errors(apps, schema_editor):
    now = timezone.now()
    for name in ("ArtifactBundleAssembly", "DifAssembly"):
        apps.get_model("files", name).objects.using(schema_editor.connection.alias).filter(state="error").update(
            error_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0011_assembly_error_at'),
    ]

    operations = [
        migrations.RunPython(date_existing_errors, migrations.RunPython.noop),
    ]
