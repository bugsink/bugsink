from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('projects', '0002_project_name_project_sentry_key'),
    ]

    operations = [
        migrations.CreateModel(
            name='Event',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('event_id', models.UUIDField(editable=False)),
                ('data', models.TextField()),
                ('timestamp', models.DateTimeField(db_index=True)),
                ('platform', models.CharField(choices=[('as3', 'As3'), ('c', 'C'), ('cfml', 'Cfml'), ('cocoa', 'Cocoa'), ('csharp', 'Csharp'), ('elixir', 'Elixir'), ('haskell', 'Haskell'), ('go', 'Go'), ('groovy', 'Groovy'), ('java', 'Java'), ('javascript', 'Javascript'), ('native', 'Native'), ('node', 'Node'), ('objc', 'Objc'), ('other', 'Other'), ('perl', 'Perl'), ('php', 'Php'), ('python', 'Python'), ('ruby', 'Ruby')], max_length=64)),
                ('level', models.CharField(blank=True, choices=[('fatal', 'Fatal'), ('error', 'Error'), ('warning', 'Warning'), ('info', 'Info'), ('debug', 'Debug')], max_length=7)),
                ('logger', models.CharField(blank=True, default='', max_length=64)),
                ('transaction', models.CharField(blank=True, default='', max_length=200)),
                ('server_name', models.CharField(blank=True, default='', max_length=255)),
                ('release', models.CharField(blank=True, default='', max_length=250)),
                ('dist', models.CharField(blank=True, default='', max_length=64)),
                ('environment', models.CharField(blank=True, default='', max_length=64)),
                ('sdk_name', models.CharField(blank=True, default='', max_length=255)),
                ('sdk_version', models.CharField(blank=True, default='', max_length=255)),
                ('project', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='projects.project')),
            ],
            options={
                'unique_together': {('project', 'event_id')},
            },
        ),
    ]
