from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0003_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='irrelevance_for_retention',
            # Given the (very) small group of test users, we can get away with just setting a default of 0 here (no
            # datamigration)
            field=models.PositiveIntegerField(default=0),
            preserve_default=False,
        ),
    ]
