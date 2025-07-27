from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0013_fix_issue_stored_event_counts"),
    ]

    operations = [
        migrations.AddField(
            model_name="grouping",
            name="grouping_key_hash",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
    ]
