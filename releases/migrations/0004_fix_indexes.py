from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0014_alter_projectmembership_project"),
        ("releases", "0003_alter_release_project"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="release",
            name="releases_re_sort_ep_5c07c8_idx",
        ),
        migrations.AddIndex(
            model_name="release",
            index=models.Index(
                fields=["project", "sort_epoch"], name="releases_re_project_1ceb8b_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="release",
            index=models.Index(
                fields=["project", "date_released"],
                name="releases_re_project_b17273_idx",
            ),
        ),
    ]
