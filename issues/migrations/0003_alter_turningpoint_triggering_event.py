# Generated by Django 4.2.13 on 2024-06-23 20:19

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0001_initial'),  # Defines Event, which we FK to below
        ('issues', '0002_initial'),  # This is the previous migration
    ]

    operations = [
        migrations.AlterField(
            model_name='turningpoint',
            name='triggering_event',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='events.event'),
        ),
    ]
