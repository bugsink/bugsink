# Generated by Django 4.2.16 on 2024-11-07 15:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0002_create_installation_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="OutboundMessage",
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
                ("attempted_at", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(null=True)),
                ("message", models.TextField()),
            ],
        ),
    ]
