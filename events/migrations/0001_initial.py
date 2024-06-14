from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Event',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='Bugsink-internal', primary_key=True, serialize=False)),
                ('server_side_timestamp', models.DateTimeField(db_index=True)),
                ('event_id', models.UUIDField(editable=False, help_text='As per the sent data')),
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
                ('has_exception', models.BooleanField()),
                ('has_logentry', models.BooleanField()),
                ('debug_info', models.CharField(blank=True, default='', max_length=255)),
                ('calculated_type', models.CharField(blank=True, default='', max_length=255)),
                ('calculated_value', models.CharField(blank=True, default='', max_length=255)),
                ('last_frame_filename', models.CharField(blank=True, default='', max_length=255)),
                ('last_frame_module', models.CharField(blank=True, default='', max_length=255)),
                ('last_frame_function', models.CharField(blank=True, default='', max_length=255)),
                ('ingest_order', models.PositiveIntegerField()),
            ],
        ),
    ]
