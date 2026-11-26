from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0009_delete_projectless_file_metadata"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="filemetadata",
            name="filemeta_project_debug_type",
        ),
        migrations.RemoveConstraint(
            model_name="filemetadata",
            name="filemeta_legacy_debug_type",
        ),
        migrations.AlterField(
            model_name="filemetadata",
            name="project",
            field=models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, to="projects.project"),
        ),
        migrations.AddConstraint(
            model_name="filemetadata",
            constraint=models.UniqueConstraint(
                fields=("project", "debug_id", "file_type"), name="filemeta_project_debug_type"),
        ),
    ]
