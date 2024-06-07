from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0005_teammembership_send_email_alerts'),
    ]

    operations = [
        migrations.AlterField(
            model_name='team',
            name='name',
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.AlterField(
            model_name='team',
            name='visibility',
            field=models.IntegerField(choices=[(1, 'Joinable'), (10, 'Visible'), (99, 'Hidden')], default=1),
        ),
        migrations.AlterField(
            model_name='teammembership',
            name='send_email_alerts',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
    ]
