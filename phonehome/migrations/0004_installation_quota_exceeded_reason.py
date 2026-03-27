from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0003_installation_ingest_quotas"),
    ]

    operations = [
        migrations.AddField(
            model_name="installation",
            name="quota_exceeded_reason",
            field=models.CharField(default="null", max_length=255),
        ),
    ]
