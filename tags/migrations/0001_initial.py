from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("events", "0019_event_storage_backend"),
        ("issues", "0012_alter_issue_calculated_type_and_more"),
        ("projects", "0011_fill_stored_event_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="TagKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=32)),
                ("mostly_unique", models.BooleanField(default=False)),
                (
                    "project",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.project",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TagValue",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("value", models.CharField(db_index=True, max_length=200)),
                (
                    "key",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="tags.tagkey"
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "unique_together": {("project", "key", "value")},
            },
        ),
        migrations.CreateModel(
            name="IssueTag",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("count", models.PositiveIntegerField(default=0)),
                (
                    "issue",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tags",
                        to="issues.issue",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.project",
                    ),
                ),
                (
                    "value",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="tags.tagvalue"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="EventTag",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="tags",
                        to="events.event",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.project",
                    ),
                ),
                (
                    "value",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="tags.tagvalue"
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="tagkey",
            index=models.Index(fields=["key"], name="tags_tagkey_key_5e8a5a_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="tagkey",
            unique_together={("project", "key")},
        ),
        migrations.AddIndex(
            model_name="issuetag",
            index=models.Index(
                fields=["issue", "value"], name="tags_issuet_issue_i_f06f20_idx"
            ),
        ),
        migrations.AlterUniqueTogether(
            name="issuetag",
            unique_together={("value", "issue")},
        ),
        migrations.AddIndex(
            model_name="eventtag",
            index=models.Index(
                fields=["event", "value"], name="tags_eventt_event_i_86e88e_idx"
            ),
        ),
        migrations.AlterUniqueTogether(
            name="eventtag",
            unique_together={("value", "event")},
        ),
    ]
