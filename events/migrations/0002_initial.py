from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('issues', '0001_initial'),  # issues.Issue is defined here, in the below we FK to that so it's a dependency
        ('events', '0001_initial'),  # This is the previous migration
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='issue',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='issues.issue'),
        ),
    ]
