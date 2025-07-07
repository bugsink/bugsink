from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0017_issue_list_indexes_must_start_with_project"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
    ]
