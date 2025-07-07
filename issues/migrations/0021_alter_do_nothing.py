from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0020_remove_objects_with_null_issue"),
    ]

    operations = [
        migrations.AlterField(
            model_name="grouping",
            name="issue",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="issues.issue"
            ),
        ),
        migrations.AlterField(
            model_name="turningpoint",
            name="issue",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="issues.issue"
            ),
        ),
    ]
