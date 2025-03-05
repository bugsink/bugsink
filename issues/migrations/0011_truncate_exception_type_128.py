from django.db import migrations
from django.db.models import F
from django.db.models.functions import Substr, Length


def truncate_exception_type_128(apps, schema_editor):
    Issue = apps.get_model("issues", "Issue")
    Issue.objects.annotate(
        l=Length('calculated_type')).filter(l__gte=128).update(calculated_type=Substr(F('calculated_type'), 1, 128))


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0010_issue_list_indexes"),
    ]

    operations = [
        migrations.RunPython(truncate_exception_type_128),
    ]
