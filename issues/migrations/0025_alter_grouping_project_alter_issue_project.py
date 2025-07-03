from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        # Django came up with 0014, whatever the reason, I'm sure that 0013 is at least required (as per comments there)
        ("projects", "0014_alter_projectmembership_project"),
        ("issues", "0024_turningpoint_project_alter_not_null"),
    ]

    operations = [
        migrations.AlterField(
            model_name="grouping",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="projects.project"
            ),
        ),
        migrations.AlterField(
            model_name="issue",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="projects.project"
            ),
        ),
    ]
