from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0032_issue_issue_global_open_issue_issue_global_muted_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["project", "is_resolved", "is_muted", "digested_event_count", "last_seen"],
                name="issue_count_open",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["project", "is_muted", "digested_event_count", "last_seen"],
                name="issue_count_muted",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["project", "is_resolved", "digested_event_count", "last_seen"],
                name="issue_count_resolved",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["project", "digested_event_count", "last_seen"],
                name="issue_count_all",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["is_resolved", "is_muted", "digested_event_count", "last_seen"],
                name="issue_global_count_open",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["is_muted", "digested_event_count", "last_seen"],
                name="issue_global_count_muted",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["is_resolved", "digested_event_count", "last_seen"],
                name="issue_global_count_resolved",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["digested_event_count", "last_seen"],
                name="issue_global_count_all",
            ),
        ),
    ]
