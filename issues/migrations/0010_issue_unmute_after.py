from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0009_issue_issues_issu_first_s_9fb0f9_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='unmute_after',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
