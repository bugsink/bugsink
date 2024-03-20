from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0010_issue_unmute_after'),
    ]

    operations = [
        migrations.AlterField(
            model_name='issue',
            name='events_at',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='issue',
            name='fixed_at',
            field=models.TextField(default=''),
        ),
    ]
