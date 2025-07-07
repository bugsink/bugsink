from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0012_project_is_deleted"),
        ("issues", "0023_turningpoint_set_project"),
    ]

    operations = [
        migrations.AlterField(
            model_name="turningpoint",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="projects.project"
            ),
        ),
    ]
