from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0002_project_name_project_sentry_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='has_releases',
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
