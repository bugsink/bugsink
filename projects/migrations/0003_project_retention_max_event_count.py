from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='retention_max_event_count',
            field=models.PositiveIntegerField(default=10000),
        ),
    ]
