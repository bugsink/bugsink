from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('events', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Grouping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('grouping_key', models.TextField()),
            ],
        ),
        migrations.CreateModel(
            name='Issue',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('ingest_order', models.PositiveIntegerField()),
                ('last_seen', models.DateTimeField()),
                ('first_seen', models.DateTimeField()),
                ('event_count', models.IntegerField()),
                ('calculated_type', models.CharField(blank=True, default='', max_length=255)),
                ('calculated_value', models.CharField(blank=True, default='', max_length=255)),
                ('transaction', models.CharField(blank=True, default='', max_length=200)),
                ('last_frame_filename', models.CharField(blank=True, default='', max_length=255)),
                ('last_frame_module', models.CharField(blank=True, default='', max_length=255)),
                ('last_frame_function', models.CharField(blank=True, default='', max_length=255)),
                ('is_resolved', models.BooleanField(default=False)),
                ('is_resolved_by_next_release', models.BooleanField(default=False)),
                ('fixed_at', models.TextField(blank=True, default='')),
                ('events_at', models.TextField(blank=True, default='')),
                ('is_muted', models.BooleanField(default=False)),
                ('unmute_on_volume_based_conditions', models.TextField(default='[]')),
                ('unmute_after', models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='TurningPoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField()),
                ('kind', models.IntegerField(choices=[(1, 'First seen'), (2, 'Resolved'), (3, 'Muted'), (4, 'Marked as regressed'), (5, 'Unmuted'), (10, 'Release info added'), (100, 'Manual annotation')])),
                ('metadata', models.TextField(default='{}')),
                ('comment', models.TextField(blank=True, default='')),
                ('issue', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='issues.issue')),
                ('triggering_event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='events.event')),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
    ]
