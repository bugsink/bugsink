from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('releases', '0002_release_semver_alter_release_is_semver_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='release',
            name='version',
            field=models.CharField(max_length=250),
        ),
    ]
