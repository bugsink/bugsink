from django.db import migrations
from django.db.models import F
from django.db.models.functions import Substr, Length


def truncate_exception_type_128(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.annotate(
        l=Length('calculated_type')).filter(l__gte=128).update(calculated_type=Substr(F('calculated_type'), 1, 128))


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0004_b_squashed"),
    ]

    operations = [
        migrations.RunPython(truncate_exception_type_128),
    ]
