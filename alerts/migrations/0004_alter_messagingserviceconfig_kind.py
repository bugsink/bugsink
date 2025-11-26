import alerts.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alerts", "0003_messagingserviceconfig_last_failure_error_message_and_more"),
    ]

    # This is the "once and for all" migration since we depend on kinds_choices rather than a list now
    operations = [
        migrations.AlterField(
            model_name="messagingserviceconfig",
            name="kind",
            field=models.CharField(
                choices=alerts.models.get_alert_service_kind_choices, default="slack", max_length=20
            ),
        ),
    ]
