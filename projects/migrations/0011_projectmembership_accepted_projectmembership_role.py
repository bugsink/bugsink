from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0010_set_single_team'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectmembership',
            name='accepted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='projectmembership',
            name='role',
            field=models.IntegerField(choices=[(0, 'Member'), (1, 'Admin')], default=0),
        ),
    ]
