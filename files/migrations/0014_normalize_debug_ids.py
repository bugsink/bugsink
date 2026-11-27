from uuid import UUID

from django.db import migrations


BATCH_SIZE = 500


def convert_debug_ids(apps, schema_editor, *, hyphenated):
    for name in ("FileMetadata", "DifAssembly"):
        objects = apps.get_model("files", name).objects.using(schema_editor.connection.alias)
        last_pk = 0
        while batch := list(objects.filter(pk__gt=last_pk, debug_id__isnull=False).only(
                "pk", "debug_id").order_by("pk")[:BATCH_SIZE]):
            last_pk = batch[-1].pk
            for obj in batch:
                debug_id = UUID(obj.debug_id)
                obj.debug_id = str(debug_id) if hyphenated else debug_id.hex
            objects.bulk_update(batch, ["debug_id"], batch_size=BATCH_SIZE)


def normalize_debug_ids(apps, schema_editor):
    # SQLite and MySQL store UUIDs without hyphens; changing the column type does not add them.
    convert_debug_ids(apps, schema_editor, hyphenated=True)


def unhyphenate_debug_ids(apps, schema_editor):
    convert_debug_ids(apps, schema_editor, hyphenated=False)


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0013_full_debug_ids'),
    ]

    operations = [
        migrations.RunPython(normalize_debug_ids, unhyphenate_debug_ids),
    ]
