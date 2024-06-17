from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('projects', '0001_initial'),
        ('events', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='project',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='projects.project'),
        ),
        migrations.AlterUniqueTogether(
            name='event',
            unique_together={('project', 'event_id'), ('issue', 'ingest_order')},
        ),
    ]