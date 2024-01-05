from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0003_project_has_releases'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='alert_on_new_issue',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='project',
            name='alert_on_regression',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='project',
            name='alert_on_unmute',
            field=models.BooleanField(default=True),
        ),
    ]
