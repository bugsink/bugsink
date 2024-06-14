from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Release',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('version', models.CharField(max_length=250)),
                ('date_released', models.DateTimeField(default=django.utils.timezone.now)),
                ('semver', models.CharField(editable=False, max_length=255)),
                ('is_semver', models.BooleanField(editable=False)),
                ('sort_epoch', models.IntegerField(editable=False)),
                ('project', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='projects.project')),
            ],
            options={
                'unique_together': {('project', 'version')},
            },
        ),
    ]
