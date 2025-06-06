# Generated by Django 4.2.16 on 2024-11-20 13:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0008_project_next_quota_check"),
    ]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="visibility",
            field=models.IntegerField(
                choices=[(1, "Joinable"), (10, "Discoverable"), (99, "Team Members")],
                default=99,
                help_text="Which users can see this project and its issues?",
            ),
        ),
    ]
