from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0028_migrate_empty_fixed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="grouping",
            name="grouping_mechanism",
            field=models.CharField(
                choices=[
                    ("none", "Mechanism-independent (explicit fingerprint)"),
                    ("bugsink-v1", "Original, default until v2.4.0 (July 2026)"),
                    ("bugsink-v2", "Value-normalized (latest)"),
                ],
                default="bugsink-v1",
                max_length=64,
            ),
            preserve_default=False,
        ),
    ]
