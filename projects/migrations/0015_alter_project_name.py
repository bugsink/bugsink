from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0014_alter_project_slug_alter_project_visibility'),
    ]

    operations = [
        migrations.AlterField(
            model_name='project',
            name='name',
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
