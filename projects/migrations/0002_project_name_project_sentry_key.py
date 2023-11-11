from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='name',
            field=models.CharField(default='asdf', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='project',
            name='sentry_key',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
    ]
