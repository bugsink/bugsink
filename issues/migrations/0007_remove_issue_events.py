from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0006_issue_is_muted_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='issue',
            name='events',
        ),
    ]
