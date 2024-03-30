from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0013_auto_20240320_1235'),
    ]

    operations = [
        migrations.AlterField(
            model_name='issue',
            name='events_at',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='issue',
            name='fixed_at',
            field=models.TextField(blank=True, default=''),
        ),
    ]
