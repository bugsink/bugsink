from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0003_event_has_exception_event_has_logentry'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='server_side_timestamp',
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
