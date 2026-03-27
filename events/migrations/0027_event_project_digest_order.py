from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0026_event_events_even_project_625413_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="project_digest_order",
            field=models.PositiveIntegerField(null=True),
        ),
    ]
