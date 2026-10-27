from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alerts", "0004_alter_messagingserviceconfig_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="messagingserviceconfig",
            name="is_active",
            field=models.BooleanField(
                default=True, help_text="Inactive services stay configured but do not receive alerts."
            ),
        ),
    ]
