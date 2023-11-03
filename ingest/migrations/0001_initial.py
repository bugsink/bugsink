from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='DecompressedEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('data', models.TextField()),
                ('timestamp', models.DateTimeField(auto_now_add=True, help_text='Server-side timestamp')),
            ],
        ),
    ]
