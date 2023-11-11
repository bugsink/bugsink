from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='debug_info',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
