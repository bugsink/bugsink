from random import random
from django.db import migrations, models
import projects.models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='name',
            field=models.CharField(default=lambda: str(random()), max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='project',
            name='sentry_key',
            field=models.CharField(default=projects.models.uuid4_hex, max_length=32, unique=True),
        ),
    ]
