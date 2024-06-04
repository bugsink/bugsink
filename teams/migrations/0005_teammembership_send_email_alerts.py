from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0004_teammembership_accepted'),
    ]

    operations = [
        migrations.AddField(
            model_name='teammembership',
            name='send_email_alerts',
            field=models.BooleanField(blank=True, default=True, null=True),
        ),
    ]
