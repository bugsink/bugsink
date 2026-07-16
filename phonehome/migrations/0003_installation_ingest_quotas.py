from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0002_installation_email_quota_usage"),
    ]

    operations = [
        migrations.AddField(
            model_name="installation",
            name="next_quota_check",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="installation",
            name="quota_exceeded_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
