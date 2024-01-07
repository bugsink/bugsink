from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0007_remove_issue_events'),
        ('events', '0007_alter_event_issue'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='issue',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='issues.issue'),
        ),
    ]
