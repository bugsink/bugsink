from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0017_project_issue_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="grouping_mechanism",
            field=models.CharField(
                choices=[
                    ("bugsink-up-until-v2.4.0", "Up until v2.4.0 (July 2026)"),
                    ("bugsink-after-v2.4.0", "After v2.4.0 (July 2026)"),
                ],
                default="bugsink-up-until-v2.4.0",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="previous_grouping_mechanism",
            field=models.CharField(
                blank=True,
                choices=[
                    ("bugsink-up-until-v2.4.0", "Up until v2.4.0 (July 2026)"),
                    ("bugsink-after-v2.4.0", "After v2.4.0 (July 2026)"),
                ],
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="grouping_mechanism_upgraded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="project",
            name="grouping_mechanism",
            field=models.CharField(
                choices=[
                    ("bugsink-up-until-v2.4.0", "Up until v2.4.0 (July 2026)"),
                    ("bugsink-after-v2.4.0", "After v2.4.0 (July 2026)"),
                ],
                default="bugsink-after-v2.4.0",
                max_length=64,
            ),
        ),
    ]
