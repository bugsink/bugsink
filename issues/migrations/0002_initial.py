from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('issues', '0001_initial'),  # This is the previous migration
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),  # Defines AUTH_USER_MODEL, which we FK to below
        ('projects', '0001_initial'),  # Defines Project, which we FK to below
    ]

    operations = [
        migrations.AddField(
            model_name='turningpoint',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='issue',
            name='project',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='projects.project'),
        ),
        migrations.AddField(
            model_name='grouping',
            name='issue',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='issues.issue'),
        ),
        migrations.AddField(
            model_name='grouping',
            name='project',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='projects.project'),
        ),
        migrations.AddIndex(
            model_name='turningpoint',
            index=models.Index(fields=['timestamp'], name='issues_turn_timesta_eaa375_idx'),
        ),
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(fields=['first_seen'], name='issues_issu_first_s_9fb0f9_idx'),
        ),
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(fields=['last_seen'], name='issues_issu_last_se_400a05_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='issue',
            unique_together={('project', 'ingest_order')},
        ),
    ]
