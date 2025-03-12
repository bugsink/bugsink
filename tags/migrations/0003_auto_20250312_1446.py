from django.db import migrations
from django.db.models import OuterRef, Subquery


def set_eventtag_digest_order(apps, schema_editor):
    EventTag = apps.get_model("tags", "EventTag")
    EventTag.objects.update(
        digest_order=Subquery(EventTag.objects.filter(pk=OuterRef('pk')).values('event__digest_order')[:1])
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tags", "0002_remove_eventtag_tags_eventt_value_i_255b9c_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(set_eventtag_digest_order, migrations.RunPython.noop),
    ]
