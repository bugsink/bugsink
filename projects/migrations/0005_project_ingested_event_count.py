# Generated by Django 4.2.13 on 2024-07-16 13:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0004_project_quota_exceeded_until'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='ingested_event_count',
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
    ]
