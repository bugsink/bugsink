from django.db import migrations, models


def set_legacy_grouping_mechanism(apps, schema_editor):
    Grouping = apps.get_model("issues", "Grouping")
    Grouping.objects.update(grouping_mechanism="bugsink-up-until-v2.4.0")


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0028_migrate_empty_fixed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="grouping",
            name="grouping_mechanism",
            field=models.CharField(
                blank=True,
                choices=[
                    ("bugsink-up-until-v2.4.0", "Up until v2.4.0 (July 2026)"),
                    ("bugsink-after-v2.4.0", "After v2.4.0 (July 2026)"),
                ],
                max_length=64,
                null=True,
            ),
        ),
        migrations.RunPython(set_legacy_grouping_mechanism, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="grouping",
            unique_together={("project", "grouping_key_hash", "grouping_mechanism")},
        ),
    ]
