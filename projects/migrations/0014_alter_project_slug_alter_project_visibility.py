from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0013_project_visibility'),
    ]

    operations = [
        migrations.AlterField(
            model_name='project',
            name='slug',
            field=models.SlugField(unique=True),
        ),
        migrations.AlterField(
            model_name='project',
            name='visibility',
            field=models.IntegerField(choices=[(1, 'Joinable'), (10, 'Visible'), (99, 'Team Members')], default=99),
        ),
    ]
