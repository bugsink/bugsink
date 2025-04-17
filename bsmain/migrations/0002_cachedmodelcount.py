from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bsmain", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CachedModelCount",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("app_label", models.CharField(max_length=255)),
                ("model_name", models.CharField(max_length=255)),
                ("count", models.PositiveIntegerField()),
                ("last_updated", models.DateTimeField(auto_now=True)),
            ],
            options={
                "unique_together": {("app_label", "model_name")},
            },
        ),
    ]
