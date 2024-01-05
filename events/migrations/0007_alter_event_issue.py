from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0007_remove_issue_events'),
        ('events', '0006_auto_20240105_1954'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='issue',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='events', to='issues.issue'),
        ),
    ]
