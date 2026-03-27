from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0025_fix_never_evict"),
        ("issues", "0025_alter_grouping_project_alter_issue_project"),
        ("projects", "0016_reset_quota_exceeded_until"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="event",
            index=models.Index(
                fields=["project", "digested_at"], name="events_even_project_625413_idx"
            ),
        ),
    ]
