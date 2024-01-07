from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ingest', '0003_decompressedevent_debug_info'),
        ('events', '0008_alter_event_issue'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='ingested_event',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='ingest.decompressedevent'),
        ),
    ]
