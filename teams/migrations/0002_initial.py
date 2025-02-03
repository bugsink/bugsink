from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('teams', '0001_initial'),  # This is the previous migration
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),  # Defines AUTH_USER_MODEL, which we FK to below
    ]

    operations = [
        migrations.AddField(
            model_name='teammembership',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterUniqueTogether(
            name='teammembership',
            unique_together={('team', 'user')},
        ),
    ]
