from django.db import migrations, models


def set_legacy_grouping_mechanism(apps, schema_editor):
    Grouping = apps.get_model("issues", "Grouping")
    Grouping.objects.update(grouping_mechanism="bugsink-v1")


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
                    ("bugsink-v1", "Original, default until v2.4.0 (July 2026)"),
                    ("bugsink-v2", "Value-normalized (latest)"),
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
