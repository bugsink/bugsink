from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0028_event_events_even_digeste_bf21dd_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="data_is_valid",
            field=models.BooleanField(default=False),
        ),
    ]
