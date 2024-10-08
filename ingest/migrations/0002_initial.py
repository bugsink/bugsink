from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("ingest", "0001_set_sqlite_wal"),
    ]

    operations = [
        migrations.CreateModel(
            name="Envelope",
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
                ("ingested_at", models.DateTimeField()),
                ("project_pk", models.IntegerField()),
                ("data", models.BinaryField()),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["ingested_at"], name="ingest_enve_ingeste_f13790_idx"
                    )
                ],
            },
        ),
    ]
