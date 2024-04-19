from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('snappea', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Task',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_name', models.CharField(max_length=255)),
                ('args', models.TextField(default='[]')),
                ('kwargs', models.TextField(default='{}')),
            ],
        ),
    ]
