from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0012_project_is_deleted"),
        ("issues", "0021_alter_do_nothing"),
    ]

    operations = [
        migrations.AddField(
            model_name="turningpoint",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                to="projects.project",
            ),
        ),
    ]
