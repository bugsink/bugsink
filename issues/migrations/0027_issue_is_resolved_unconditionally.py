from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0026_alter_turningpoint_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="is_resolved_unconditionally",
            field=models.BooleanField(default=False),
        ),
    ]
