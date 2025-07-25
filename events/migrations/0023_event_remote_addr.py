from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0022_alter_event_project'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='remote_addr',
            field=models.GenericIPAddressField(blank=True, default=None, null=True),
        ),
    ]
