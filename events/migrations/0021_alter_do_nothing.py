from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0021_alter_do_nothing"),
        ("events", "0020_remove_events_with_null_issue_or_grouping"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="grouping",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="issues.grouping"
            ),
        ),
        migrations.AlterField(
            model_name="event",
            name="issue",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="issues.issue"
            ),
        ),
    ]
