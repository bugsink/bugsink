from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('projects', '0005_projectmembership_project_users'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='projectmembership',
            unique_together={('project', 'user')},
        ),
    ]
