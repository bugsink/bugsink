from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0013_delete_objects_pointing_to_null_project"),
    ]

    operations = [
        migrations.AlterField(
            model_name="projectmembership",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="projects.project"
            ),
        ),
    ]
