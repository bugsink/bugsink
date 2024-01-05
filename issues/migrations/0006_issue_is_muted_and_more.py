from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0005_issue_is_resolved_by_next_release'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='is_muted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='issue',
            name='unmute_on_volume_based_conditions',
            field=models.TextField(default='[]'),
        ),
    ]
