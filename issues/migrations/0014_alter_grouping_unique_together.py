from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0011_fill_stored_event_count"),
        ("issues", "0013_fix_issue_stored_event_counts"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="grouping",
            unique_together={("project", "grouping_key")},
        ),
    ]
