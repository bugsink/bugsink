# Generated by Django 4.2.11 on 2024-04-26 08:08

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0018_fill_denormalized_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='event',
            name='ingested_event',
        ),
    ]