from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0014_alter_projectmembership_project"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="quota_exceeded_reason",
            field=models.CharField(default="null", max_length=255),
        ),
    ]
