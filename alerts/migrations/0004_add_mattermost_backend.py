# Generated manually for adding Mattermost backend option

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0003_messagingserviceconfig_last_failure_error_message_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="messagingserviceconfig",
            name="kind",
            field=models.CharField(
                choices=[("slack", "Slack"), ("mattermost", "Mattermost")],
                default="slack",
                max_length=20,
            ),
        ),
    ]
