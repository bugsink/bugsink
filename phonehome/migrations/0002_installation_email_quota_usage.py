# Generated by Django 4.2.21 on 2025-07-28 12:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0001_b_squashed_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="installation",
            name="email_quota_usage",
            field=models.TextField(default='{"per_month": {}}'),
        ),
    ]
