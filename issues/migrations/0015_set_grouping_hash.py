import hashlib
from django.db import migrations


def set_grouping_hash(apps, schema_editor):
    Grouping = apps.get_model("issues", "Grouping")
    for grouping in Grouping.objects.all():
        grouping.grouping_key_hash = hashlib.sha256(grouping.grouping_key.encode()).hexdigest()
        grouping.save()


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0014_grouping_grouping_key_hash"),
    ]

    operations = [
        migrations.RunPython(set_grouping_hash),
    ]
