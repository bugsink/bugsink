from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('projects', '0002_project_name_project_sentry_key'),
    ]

    operations = [
        migrations.CreateModel(
            name='Release',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('version', models.CharField(max_length=255)),
                ('date_released', models.DateTimeField(default=django.utils.timezone.now)),
                ('is_semver', models.BooleanField()),
                ('sort_epoch', models.IntegerField()),
                ('project', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='projects.project')),
            ],
            options={
                'unique_together': {('project', 'version')},
            },
        ),
    ]
