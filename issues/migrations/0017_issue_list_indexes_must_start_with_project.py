from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0016_alter_grouping_unique_together"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="issue",
            name="issues_issu_first_s_9fb0f9_idx",
        ),
        migrations.RemoveIndex(
            model_name="issue",
            name="issues_issu_last_se_400a05_idx",
        ),
        migrations.RemoveIndex(
            model_name="issue",
            name="issues_issu_is_reso_eaf32b_idx",
        ),
        migrations.RemoveIndex(
            model_name="issue",
            name="issues_issu_is_mute_6fe7fc_idx",
        ),
        migrations.RemoveIndex(
            model_name="issue",
            name="issues_issu_is_reso_0b6923_idx",
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["project", "is_resolved", "is_muted", "last_seen"],
                name="issue_list_open",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["project", "is_muted", "last_seen"], name="issue_list_muted"
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(
                fields=["project", "is_resolved", "last_seen"],
                name="issue_list_resolved",
            ),
        ),
        migrations.AddIndex(
            model_name="issue",
            index=models.Index(fields=["project", "last_seen"], name="issue_list_all"),
        ),
    ]
