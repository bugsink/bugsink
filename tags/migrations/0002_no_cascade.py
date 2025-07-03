from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tags", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="eventtag",
            name="value",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="tags.tagvalue"
            ),
        ),
        migrations.AlterField(
            model_name="issuetag",
            name="key",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="tags.tagkey"
            ),
        ),
        migrations.AlterField(
            model_name="issuetag",
            name="value",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="tags.tagvalue"
            ),
        ),
        migrations.AlterField(
            model_name="tagvalue",
            name="key",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING, to="tags.tagkey"
            ),
        ),
    ]
