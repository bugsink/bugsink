from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0004_issue_events_at_issue_fixed_at_issue_is_resolved'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='is_resolved_by_next_release',
            field=models.BooleanField(default=False),
        ),
    ]
