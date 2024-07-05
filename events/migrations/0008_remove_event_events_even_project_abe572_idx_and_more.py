# Generated by Django 4.2.13 on 2024-06-24 20:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0007_set_never_evict'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='event',
            name='events_even_project_abe572_idx',
        ),
        migrations.AddIndex(
            model_name='event',
            index=models.Index(fields=['project', 'never_evict', 'server_side_timestamp', 'irrelevance_for_retention'], name='events_even_project_adcdee_idx'),
        ),
    ]