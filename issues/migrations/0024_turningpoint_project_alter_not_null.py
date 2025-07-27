from django.db import migrations, models
import django.db.models.deletion


def delete_turningpoints_pointing_to_null_project(apps, schema_editor):
    # In 0023_turningpoint_set_project, we set the project field for TurningPoint to the associated Issue's project.
    # _However_, at that point in time in our migration-history, Issue's project field was still nullable, and the big
    # null-project-fk-deleting migration (projects/migrations/0013_delete_objects_pointing_to_null_project.py) is _sure_
    # not to have run yet (it depends on the present migration). (it wouldn't delete TurningPoints anyway, but it would
    # delete project-less Issues). Anyway, we just take care of the TurningPoints here (that's ok as per 0013_delete_...
    # logic, i.e. no-project means no way to access) and it's also possible since they are on the edge of our object
    # graph.
    TurningPoint = apps.get_model("issues", "TurningPoint")
    TurningPoint.objects.filter(project__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0012_project_is_deleted"),
        ("issues", "0023_turningpoint_set_project"),
    ]

    operations = [
        migrations.RunPython(
            delete_turningpoints_pointing_to_null_project,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="turningpoint",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="projects.project"
            ),
        ),
    ]
