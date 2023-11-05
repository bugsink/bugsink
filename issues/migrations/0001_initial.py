from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('ingest', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Issue',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('hash', models.CharField(max_length=32)),
                ('events', models.ManyToManyField(to='ingest.decompressedevent')),
            ],
        ),
    ]
