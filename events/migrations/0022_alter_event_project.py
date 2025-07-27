from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        # Django came up with 0014, whatever the reason, I'm sure that 0013 is at least required (as per comments there)
        ("projects", "0014_alter_projectmembership_project"),
        ("events", "0021_alter_do_nothing"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="projects.project"
            ),
        ),
    ]
