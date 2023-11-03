from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
        ('ingest', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='decompressedevent',
            name='project',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='projects.project'),
        ),
    ]
