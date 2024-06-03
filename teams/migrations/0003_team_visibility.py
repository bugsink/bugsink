from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0002_create_single_team'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='visibility',
            field=models.IntegerField(choices=[(0, 'Public'), (1, 'Visible'), (2, 'Hidden')], default=0),
        ),
    ]
