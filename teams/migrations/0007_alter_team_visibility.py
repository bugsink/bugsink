# Generated by Django 4.2.13 on 2024-06-06 12:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0006_alter_team_name_alter_team_visibility_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='team',
            name='visibility',
            field=models.IntegerField(choices=[(1, 'Joinable'), (10, 'Visible'), (99, 'Hidden')], default=10),
        ),
    ]