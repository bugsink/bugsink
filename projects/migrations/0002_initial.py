from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('teams', '0001_initial'),  # Defines Team, which we FK to below
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),  # Defines AUTH_USER_MODEL, which we FK to below
        ('projects', '0001_initial'),  # This is the previous migration
    ]

    operations = [
        migrations.AddField(
            model_name='projectmembership',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='project',
            name='team',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='teams.team'),
        ),
        migrations.AddField(
            model_name='project',
            name='users',
            field=models.ManyToManyField(blank=True, through='projects.ProjectMembership', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterUniqueTogether(
            name='projectmembership',
            unique_together={('project', 'user')},
        ),
    ]
