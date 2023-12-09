from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('releases', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='release',
            name='semver',
            field=models.CharField(default='', editable=False, max_length=255),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='release',
            name='is_semver',
            field=models.BooleanField(editable=False),
        ),
        migrations.AlterField(
            model_name='release',
            name='sort_epoch',
            field=models.IntegerField(editable=False),
        ),
    ]
