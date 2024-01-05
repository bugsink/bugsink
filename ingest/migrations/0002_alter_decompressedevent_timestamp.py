from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('ingest', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='decompressedevent',
            name='timestamp',
            field=models.DateTimeField(default=django.utils.timezone.now, help_text='Server-side timestamp'),
        ),
    ]
