from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ingest', '0002_alter_decompressedevent_timestamp'),
    ]

    operations = [
        migrations.AddField(
            model_name='decompressedevent',
            name='debug_info',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
