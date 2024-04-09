from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0014_fill_ingest_order'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='ingest_order',
            field=models.PositiveIntegerField(),
        ),
    ]
