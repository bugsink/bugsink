from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0027_event_project_digest_order"),
        ("issues", "0025_alter_grouping_project_alter_issue_project"),
        ("projects", "0016_reset_quota_exceeded_until"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="event",
            index=models.Index(
                fields=["digested_at", "digest_order"],
                name="events_even_digeste_bf21dd_idx",
            ),
        ),
    ]
