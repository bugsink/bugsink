from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0021_alter_do_nothing"),
        ("tags", "0003_remove_objects_with_null_issue"),
    ]

    operations = [
        migrations.AlterField(
            model_name="eventtag",
            name="issue",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="event_tags",
                to="issues.issue",
            ),
        ),
        migrations.AlterField(
            model_name="issuetag",
            name="issue",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="tags",
                to="issues.issue",
            ),
        ),
    ]
