from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0006_recalculate_installation_next_quota_check"),
    ]

    operations = [
        migrations.AddField(
            model_name="installation",
            name="email_sending_diagnostics",
            field=models.TextField(default='{"attempts": []}'),
        ),
    ]
