from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0008_issue_event_count_issue_first_seen_issue_last_seen'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(fields=['first_seen'], name='issues_issu_first_s_9fb0f9_idx'),
        ),
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(fields=['last_seen'], name='issues_issu_last_se_400a05_idx'),
        ),
    ]
