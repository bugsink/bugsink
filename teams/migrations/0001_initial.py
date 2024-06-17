from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Team',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255, unique=True)),
                ('slug', models.SlugField()),
                ('visibility', models.IntegerField(choices=[(1, 'Joinable'), (10, 'Discoverable'), (99, 'Hidden')], default=10)),
            ],
        ),
        migrations.CreateModel(
            name='TeamMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('send_email_alerts', models.BooleanField(blank=True, default=None, null=True)),
                ('role', models.IntegerField(choices=[(0, 'Member'), (1, 'Admin')], default=0)),
                ('accepted', models.BooleanField(default=False)),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='teams.team')),
            ],
        ),
    ]
