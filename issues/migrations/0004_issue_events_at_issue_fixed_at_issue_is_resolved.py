from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0003_alter_issue_events'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='events_at',
            field=models.TextField(default='[]'),
        ),
        migrations.AddField(
            model_name='issue',
            name='fixed_at',
            field=models.TextField(default='[]'),
        ),
        migrations.AddField(
            model_name='issue',
            name='is_resolved',
            field=models.BooleanField(default=False),
        ),
    ]
