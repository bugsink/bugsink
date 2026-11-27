from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0012_date_existing_assembly_errors'),
    ]

    operations = [
        migrations.AlterField(
            model_name='difassembly',
            name='debug_id',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='filemetadata',
            name='debug_id',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
