from django.db import migrations

from bugsink.transaction import immediate_atomic


BATCH_SIZE = 100


def delete_projectless_file_metadata(apps, schema_editor):
    FileMetadata = apps.get_model("files", "FileMetadata")
    using = schema_editor.connection.alias
    metadata = FileMetadata.objects.using(using)
    while True:
        with immediate_atomic(using=using):
            ids = list(metadata.filter(project__isnull=True).order_by("pk").values_list("pk", flat=True)[:BATCH_SIZE])
            if not ids:
                break
            metadata.filter(pk__in=ids).delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("files", "0008_scope_legacy_file_metadata"),
    ]

    operations = [
        migrations.RunPython(delete_projectless_file_metadata, migrations.RunPython.noop),
    ]
