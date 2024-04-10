from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0016_alter_event_unique_together'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='last_frame_filename',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='event',
            name='last_frame_function',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='event',
            name='last_frame_module',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
