# Generated by Django 4.2.13 on 2024-06-12 14:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_emailverification'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='send_email_alerts',
            field=models.BooleanField(blank=True, default=True),
        ),
    ]