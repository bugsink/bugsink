from django.db import migrations


def create_installation_id(apps, schema_editor):
    Installation = apps.get_model("phonehome", "Installation")
    Installation.objects.create()  # id is implied (it's a uuid)


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_installation_id),
    ]
