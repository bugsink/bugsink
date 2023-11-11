from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0002_event_debug_info'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='has_exception',
            field=models.BooleanField(default=False),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='event',
            name='has_logentry',
            field=models.BooleanField(default=False),
            preserve_default=False,
        ),
    ]
