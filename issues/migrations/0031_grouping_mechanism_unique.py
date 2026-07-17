from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0030_grouping_mechanism_data"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="grouping",
            unique_together={("project", "grouping_key_hash", "grouping_mechanism")},
        ),
    ]
