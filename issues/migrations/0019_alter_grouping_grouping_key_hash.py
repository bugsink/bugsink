from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0018_issue_is_deleted"),
    ]

    operations = [
        migrations.AlterField(
            model_name="grouping",
            name="grouping_key_hash",
            field=models.CharField(max_length=64, null=True),
        ),
    ]
