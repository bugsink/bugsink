from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0003_team_visibility'),
    ]

    operations = [
        migrations.AddField(
            model_name='teammembership',
            name='accepted',
            field=models.BooleanField(default=False),
        ),
    ]
