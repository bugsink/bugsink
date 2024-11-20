# Generated by Django 4.2.16 on 2024-11-11 12:48

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0003_outboundmessage"),
    ]

    operations = [
        migrations.AddField(
            model_name="installation",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
    ]