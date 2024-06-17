from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('slug', models.SlugField(unique=True)),
                ('sentry_key', models.UUIDField(default=uuid.uuid4, editable=False)),
                ('has_releases', models.BooleanField(default=False, editable=False)),
                ('alert_on_new_issue', models.BooleanField(default=True)),
                ('alert_on_regression', models.BooleanField(default=True)),
                ('alert_on_unmute', models.BooleanField(default=True)),
                ('visibility', models.IntegerField(choices=[(1, 'Joinable'), (10, 'Discoverable'), (99, 'Team Members')], default=99)),
            ],
        ),
        migrations.CreateModel(
            name='ProjectMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('send_email_alerts', models.BooleanField(default=None, null=True)),
                ('role', models.IntegerField(choices=[(0, 'Member'), (1, 'Admin')], default=0)),
                ('accepted', models.BooleanField(default=False)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='projects.project')),
            ],
        ),
    ]
