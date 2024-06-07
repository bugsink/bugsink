from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0011_projectmembership_accepted_projectmembership_role'),
    ]

    operations = [
        migrations.AlterField(
            model_name='projectmembership',
            name='send_email_alerts',
            field=models.BooleanField(default=None, null=True),
        ),
    ]
