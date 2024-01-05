from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0004_event_server_side_timestamp'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='issue',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='issues.issue'),
        ),
    ]
